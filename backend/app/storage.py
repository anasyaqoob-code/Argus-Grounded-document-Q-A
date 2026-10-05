"""SQLite persistence for chat sessions, messages, feedback, and documents.

Two logical areas live in this file:

  1. **Chat persistence** — sessions, messages, feedback. Used by
     ``memory.py`` and the Streamlit UI. Unchanged from the prior version.

  2. **Document registry** — records uploaded documents, their on-disk
     paths, indexing status, and page/chunk counts. Added for the FastAPI
     ``main.py`` surface, which needs to persist documents across the
     request boundary (upload in one request, query in a later request).

Finding #7 fix (user isolation) applies to both areas: every read and
write is scoped to a ``user_id``.

Authentication adds a third area: **users**. The ``users`` table stores
email + bcrypt password hash. Registration and login live in
``auth.py``; this file owns the persistence layer only.

Analytics adds a fourth area: **auth_events**. Signups, logins, and
logouts are recorded as append-only events so the admin dashboard can
aggregate them into time series. Events are best-effort: a failed write
must never break the auth request that triggered it.

A fifth area — **query_metrics** — decouples per-query RAG evaluation
metrics from the messages they came from. The metrics live in their own
table so deleting a session, purging a document, or clearing history
doesn't erase the analytics. The eval block is still written into the
message metadata for the export feature; ``query_metrics`` is the
canonical source for the dashboard.

A sixth area — **password_resets** — holds short-lived tokens for the
password recovery flow. Tokens expire after 30 minutes and are deleted
the moment they're consumed.

A seventh concern — **google_sub** on the ``users`` table — stores the
Google account identifier for users who signed in with Google. Set on
first OAuth login; unique when present.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

# Anchor to this file, not the CWD.
_THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = _THIS_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
CHROMA_DIR = DATA_DIR / "chroma"

DEFAULT_USER_ID = "anon"

logger = logging.getLogger("argus.storage")


# ===========================================================================
# Connection + schema
# ===========================================================================
@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create base schema (idempotent), then apply forward migrations."""
    with _conn() as c:
        c.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_users_email
                ON users(email);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                user_id TEXT NOT NULL DEFAULT '{DEFAULT_USER_ID}'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_user
                ON sessions(user_id, updated_at);
            CREATE TABLE IF NOT EXISTS feedback (
                message_id INTEGER PRIMARY KEY,
                rating TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                page_count INTEGER,
                chunk_count INTEGER,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                user_id TEXT NOT NULL DEFAULT '{DEFAULT_USER_ID}'
            );
            CREATE INDEX IF NOT EXISTS idx_documents_user
                ON documents(user_id, created_at);
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                created_at REAL NOT NULL,
                user_id TEXT NOT NULL DEFAULT '{DEFAULT_USER_ID}'
            );
            CREATE INDEX IF NOT EXISTS idx_summaries_user
                ON session_summaries(user_id, created_at);
            CREATE TABLE IF NOT EXISTS auth_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                event TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_auth_events_time
                ON auth_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_auth_events_user
                ON auth_events(user_id, created_at);
            CREATE TABLE IF NOT EXISTS query_metrics (
                message_id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                faithfulness REAL,
                context_precision REAL,
                chunks_retrieved INTEGER,
                abstained INTEGER NOT NULL DEFAULT 0,
                verification_passed INTEGER,
                latency_ms REAL,
                composite REAL
            );
            CREATE INDEX IF NOT EXISTS idx_query_metrics_time
                ON query_metrics(created_at);
            CREATE INDEX IF NOT EXISTS idx_query_metrics_user
                ON query_metrics(user_id, created_at);
            CREATE TABLE IF NOT EXISTS password_resets (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_password_resets_user
                ON password_resets(user_id);
            CREATE INDEX IF NOT EXISTS idx_password_resets_expires
                ON password_resets(expires_at);
            """
        )

        # Forward migration: user_id on sessions (older DBs).
        cols = {row["name"] for row in c.execute("PRAGMA table_info(sessions)")}
        if "user_id" not in cols:
            c.execute(
                f"ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL "
                f"DEFAULT '{DEFAULT_USER_ID}'"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user "
                "ON sessions(user_id, updated_at)"
            )

        # Forward migration: is_admin on users (older DBs).
        user_cols = {row["name"] for row in c.execute("PRAGMA table_info(users)")}
        if "is_admin" not in user_cols:
            c.execute(
                "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )

        # Forward migration: google_sub on users (for Google OAuth).
        user_cols_2 = {row["name"] for row in c.execute("PRAGMA table_info(users)")}
        if "google_sub" not in user_cols_2:
            c.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub "
                "ON users(google_sub) WHERE google_sub IS NOT NULL"
            )


def backfill_user_id(
    old_user: str = DEFAULT_USER_ID,
    new_user: str = DEFAULT_USER_ID,
) -> int:
    """Reassign all sessions owned by ``old_user`` to ``new_user``."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE sessions SET user_id=? WHERE user_id=?",
            (new_user, old_user),
        )
        return cur.rowcount or 0


# ===========================================================================
# Factory — what main.py calls
# ===========================================================================
def get_storage():
    """Return this module as the storage handle.

    ``main.py`` does ``storage = get_storage()`` and then calls
    ``storage.create_document(...)`` etc. Because we return the module
    itself, those calls resolve to the module-level functions below.
    """
    import sys

    return sys.modules[__name__]


# ===========================================================================
# Users (auth)
# ===========================================================================
def create_user(
    email: str,
    password_hash: str,
) -> Optional[str]:
    """Insert a new user. Returns the new user id, or None if the email exists.

    Uses ``INSERT OR IGNORE`` so a concurrent registration for the same
    email doesn't raise — one caller wins, the other gets ``None``.

    If the email matches the ``ADMIN_EMAIL`` env var, the new user is
    promoted to admin. This is the only mechanism that grants admin on
    a fresh database; afterwards, ``set_admin`` can flip the flag.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return None

    uid = uuid.uuid4().hex
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (uid, normalized, password_hash, now),
        )
        if (cur.rowcount or 0) == 0:
            return None

        admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
        if admin_email and normalized == admin_email:
            c.execute("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
            logger.info("Promoted %s to admin via ADMIN_EMAIL", normalized)

    return uid


def get_user_by_email(email: str) -> Optional[dict]:
    """Look up a user by email. Returns None if not found."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT id, email, password_hash, created_at FROM users "
            "WHERE email = ? LIMIT 1",
            (normalized,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Look up a user by id. Returns None if not found."""
    if not user_id:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT id, email, password_hash, created_at FROM users "
            "WHERE id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def migrate_anon_data_to_user(new_user_id: str) -> int:
    """Reassign every row owned by the 'anon' sentinel to ``new_user_id``.

    Called once, on first registration, so pre-auth data carries over.
    Idempotent: running it again is a no-op because no rows match after
    the first pass.

    Returns the number of sessions migrated (useful for logging).
    """
    if not new_user_id or new_user_id == DEFAULT_USER_ID:
        return 0
    with _conn() as c:
        cur = c.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id = ?",
            (new_user_id, DEFAULT_USER_ID),
        )
        migrated = cur.rowcount or 0
        c.execute(
            "UPDATE documents SET user_id = ? WHERE user_id = ?",
            (new_user_id, DEFAULT_USER_ID),
        )
        c.execute(
            "UPDATE session_summaries SET user_id = ? WHERE user_id = ?",
            (new_user_id, DEFAULT_USER_ID),
        )
    return migrated


# ===========================================================================
# Admin flag + auth events — used by the analytics dashboard
# ===========================================================================
def is_admin(user_id: str) -> bool:
    """Return True if the user has the admin flag set."""
    if not user_id:
        return False
    with _conn() as c:
        row = c.execute(
            "SELECT is_admin FROM users WHERE id=? LIMIT 1",
            (user_id,),
        ).fetchone()
    return bool(row and row["is_admin"])


def set_admin(user_id: str, is_admin: bool = True) -> bool:
    """Grant or revoke admin. Returns True if a row was updated."""
    if not user_id:
        return False
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET is_admin=? WHERE id=?",
            (1 if is_admin else 0, user_id),
        )
        return (cur.rowcount or 0) > 0


def get_admin_by_email(email: str) -> Optional[dict]:
    """Same as get_user_by_email but includes the is_admin column."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT id, email, password_hash, created_at, is_admin "
            "FROM users WHERE email = ? LIMIT 1",
            (normalized,),
        ).fetchone()
    return dict(row) if row else None


def record_auth_event(user_id: str, event: str) -> None:
    """Record a signup, login, or logout event.

    ``event`` is expected to be one of: 'signup', 'login', 'logout'.
    Failures are logged but never raised — a broken analytics write
    must not break the auth request that triggered it.
    """
    if not user_id or not event:
        return
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO auth_events (user_id, event, created_at) "
                "VALUES (?, ?, ?)",
                (user_id, event, time.time()),
            )
    except Exception:
        logger.exception(
            "Failed to record auth event %s for user %s", event, user_id
        )


# ===========================================================================
# Analytics — aggregations for the admin dashboard
#
# Every counter accepts an optional ``since`` timestamp. When set, the
# count is scoped to rows created at or after that time. The admin
# summary endpoint uses this to make the range selector meaningful —
# "30d" shows what changed in the last 30 days, "All" shows lifetime.
# ===========================================================================
def count_users(since: Optional[float] = None) -> int:
    """Total registered users, optionally scoped to a start timestamp."""
    q = "SELECT COUNT(*) AS n FROM users"
    params: list = []
    if since is not None:
        q += " WHERE created_at >= ?"
        params.append(since)
    with _conn() as c:
        row = c.execute(q, params).fetchone()
    return int(row["n"]) if row else 0


def count_documents_total(since: Optional[float] = None) -> int:
    """Total documents across all users, optionally scoped by time."""
    q = "SELECT COUNT(*) AS n FROM documents"
    params: list = []
    if since is not None:
        q += " WHERE created_at >= ?"
        params.append(since)
    with _conn() as c:
        row = c.execute(q, params).fetchone()
    return int(row["n"]) if row else 0


def count_messages_total(since: Optional[float] = None) -> int:
    """Total messages across all sessions, optionally scoped by time."""
    q = "SELECT COUNT(*) AS n FROM messages"
    params: list = []
    if since is not None:
        q += " WHERE created_at >= ?"
        params.append(since)
    with _conn() as c:
        row = c.execute(q, params).fetchone()
    return int(row["n"]) if row else 0


def count_sessions_total(since: Optional[float] = None) -> int:
    """Total sessions across all users, optionally scoped by time.

    Unlike ``count_sessions(user_id)``, this does NOT filter by user —
    that's the whole point. The admin summary card needs the global
    count, and ``count_sessions(user_id=None)`` matches nothing because
    the WHERE clause compares against NULL.
    """
    q = "SELECT COUNT(*) AS n FROM sessions"
    params: list = []
    if since is not None:
        q += " WHERE created_at >= ?"
        params.append(since)
    with _conn() as c:
        row = c.execute(q, params).fetchone()
    return int(row["n"]) if row else 0


def auth_events_by_day(
    event: Optional[str] = None,
    days: int = 30,
) -> list[dict]:
    """Return per-day counts of auth events for the last N days.

    ``event`` filters to a single event type ('signup', 'login', 'logout').
    Pass None for the combined total across all event types.

    Returns a list of {"date": "YYYY-MM-DD", "count": N}, sorted ascending.
    Days with no events are omitted; the caller can fill gaps if needed.

    Special case: ``days=0`` returns lifetime data with no cutoff.
    """
    if days > 0:
        cutoff = time.time() - (days * 86400)
    else:
        cutoff = 0.0

    with _conn() as c:
        if event:
            rows = c.execute(
                """
                SELECT date(created_at, 'unixepoch') AS day,
                       COUNT(*) AS n
                FROM auth_events
                WHERE created_at >= ? AND event = ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (cutoff, event),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT date(created_at, 'unixepoch') AS day,
                       COUNT(*) AS n
                FROM auth_events
                WHERE created_at >= ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (cutoff,),
            ).fetchall()
    return [{"date": r["day"], "count": int(r["n"])} for r in rows]


def sessions_by_day(days: int = 30) -> list[dict]:
    """Return per-day session creation counts for the last N days.

    Special case: ``days=0`` returns lifetime data with no cutoff.
    """
    if days > 0:
        cutoff = time.time() - (days * 86400)
    else:
        cutoff = 0.0

    with _conn() as c:
        rows = c.execute(
            """
            SELECT date(created_at, 'unixepoch') AS day,
                   COUNT(*) AS n
            FROM sessions
            WHERE created_at >= ?
            GROUP BY day
            ORDER BY day ASC
            """,
            (cutoff,),
        ).fetchall()
    return [{"date": r["day"], "count": int(r["n"])} for r in rows]


# ===========================================================================
# Query metrics — durable eval data, decoupled from messages
#
# Metrics live in their own table. The message row and its metadata may
# be deleted (session cleanup, document purge), but the metric row
# survives. The dashboard reads from here, not from message metadata.
# ===========================================================================
def record_query_metric(
    *,
    message_id: int,
    user_id: str,
    session_id: str,
    eval_block: dict,
) -> None:
    """Write an eval block to the durable metrics table.

    Called once per assistant turn, right after the message row is
    inserted. Best-effort — a failed write must never break the query
    response.
    """
    if not message_id or not user_id:
        return
    try:
        with _conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO query_metrics (
                    message_id, user_id, session_id, created_at,
                    faithfulness, context_precision, chunks_retrieved,
                    abstained, verification_passed, latency_ms, composite
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(message_id),
                    user_id,
                    session_id,
                    time.time(),
                    eval_block.get("faithfulness"),
                    eval_block.get("context_precision"),
                    eval_block.get("chunks_retrieved"),
                    1 if eval_block.get("abstained") else 0,
                    (
                        1
                        if eval_block.get("verification_passed") is True
                        else (
                            0
                            if eval_block.get("verification_passed") is False
                            else None
                        )
                    ),
                    eval_block.get("latency_ms"),
                    eval_block.get("composite"),
                ),
            )
    except Exception:
        logger.exception("Failed to record query metric")


def rag_metrics_aggregate(days: int = 30) -> dict:
    """Aggregate RAG evaluation metrics from the durable metrics table.

    Reads ``query_metrics``, not ``messages.metadata_json``. The
    metrics survive session deletion and document purges.

    Special case: ``days=0`` returns lifetime data with no cutoff.
    """
    if days > 0:
        cutoff = time.time() - (days * 86400)
    else:
        cutoff = 0.0

    with _conn() as c:
        row = c.execute(
            """
            SELECT
                COUNT(*) AS n,
                AVG(faithfulness) AS avg_f,
                COUNT(faithfulness) AS n_f,
                AVG(context_precision) AS avg_p,
                COUNT(context_precision) AS n_p,
                AVG(latency_ms) AS avg_l,
                COUNT(latency_ms) AS n_l,
                AVG(composite) AS avg_c,
                COUNT(composite) AS n_c,
                SUM(abstained) AS n_abst,
                SUM(CASE WHEN verification_passed IS NOT NULL THEN 1 ELSE 0 END) AS n_v,
                SUM(CASE WHEN verification_passed = 1 THEN 1 ELSE 0 END) AS n_v_pass
            FROM query_metrics
            WHERE created_at >= ?
            """,
            (cutoff,),
        ).fetchone()

    n = int(row["n"] or 0)
    n_v = int(row["n_v"] or 0)
    return {
        "sample_size": n,
        "avg_faithfulness": row["avg_f"],
        "avg_context_precision": row["avg_p"],
        "avg_latency_ms": row["avg_l"],
        "avg_composite": row["avg_c"],
        "abstention_rate": (row["n_abst"] / n) if n else None,
        "verification_pass_rate": (row["n_v_pass"] / n_v) if n_v else None,
        "counts": {
            "faithfulness": int(row["n_f"] or 0),
            "context_precision": int(row["n_p"] or 0),
            "latency": int(row["n_l"] or 0),
            "composite": int(row["n_c"] or 0),
            "verification": n_v,
        },
    }


def recent_queries(limit: int = 50) -> list[dict]:
    """Recent eval rows, joined to messages when the message still exists.

    LEFT JOIN because a purged session may have removed the message row
    but left the metric row — we still want to show the metric, with a
    placeholder for the question preview.
    """
    with _conn() as c:
        rows = c.execute(
            """
            SELECT
                q.message_id, q.session_id, q.user_id, q.created_at,
                q.faithfulness, q.context_precision, q.composite,
                q.abstained, q.latency_ms,
                COALESCE(
                    substr(m.content, 1, 140),
                    '(question no longer available)'
                ) AS question_preview
            FROM query_metrics q
            LEFT JOIN messages m ON m.id = q.message_id
            ORDER BY q.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "message_id": r["message_id"],
            "session_id": r["session_id"],
            "user_id": r["user_id"],
            "created_at": r["created_at"],
            "question_preview": r["question_preview"],
            "faithfulness": r["faithfulness"],
            "context_precision": r["context_precision"],
            "composite": r["composite"],
            "abstained": bool(r["abstained"]),
            "latency_ms": r["latency_ms"],
        }
        for r in rows
    ]


# ===========================================================================
# Password resets — short-lived tokens for the recovery flow
# ===========================================================================
def create_password_reset(
    user_id: str,
    token: str,
    ttl_seconds: int = 1800,
) -> None:
    """Store a reset token for a user. Deletes any prior tokens for the
    same user, so only the most recent request is valid."""
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
        c.execute(
            "INSERT INTO password_resets (token, user_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (token, user_id, now + ttl_seconds, now),
        )


def consume_password_reset(token: str) -> Optional[str]:
    """Validate a token and delete it. Returns the user_id, or None.

    A consumed token is deleted immediately, so it cannot be reused
    even within its validity window. An expired token is also deleted.
    """
    if not token:
        return None
    now = time.time()
    with _conn() as c:
        row = c.execute(
            "SELECT user_id, expires_at FROM password_resets "
            "WHERE token=? LIMIT 1",
            (token,),
        ).fetchone()
        if not row:
            return None
        if float(row["expires_at"]) < now:
            c.execute("DELETE FROM password_resets WHERE token=?", (token,))
            return None
        user_id = row["user_id"]
        c.execute("DELETE FROM password_resets WHERE token=?", (token,))
    return user_id


def update_user_password(user_id: str, password_hash: str) -> bool:
    """Replace a user's password hash. Returns True on success."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hash, user_id),
        )
        return (cur.rowcount or 0) > 0


def purge_expired_password_resets() -> int:
    """Delete tokens whose expiry has passed. Called on startup."""
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM password_resets WHERE expires_at < ?",
            (time.time(),),
        )
        return cur.rowcount or 0


# ===========================================================================
# Google OAuth — link users to their Google account identifier
# ===========================================================================
def get_user_by_google_sub(google_sub: str) -> Optional[dict]:
    """Look up a user by their Google sub (stable unique id)."""
    if not google_sub:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT id, email, password_hash, created_at, is_admin, google_sub "
            "FROM users WHERE google_sub = ? LIMIT 1",
            (google_sub,),
        ).fetchone()
    return dict(row) if row else None


def create_google_user(email: str, google_sub: str) -> Optional[str]:
    """Create a user whose only login method is Google.

    password_hash is set to the string ``*``, which bcrypt will never
    verify against — so password login is effectively disabled until
    the user sets one via password reset.
    """
    normalized = (email or "").strip().lower()
    if not normalized or not google_sub:
        return None
    uid = uuid.uuid4().hex
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO users "
            "(id, email, password_hash, created_at, google_sub) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, normalized, "*", now, google_sub),
        )
        if (cur.rowcount or 0) == 0:
            return None

        admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
        if admin_email and normalized == admin_email:
            c.execute("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
    return uid


def link_google_sub(user_id: str, google_sub: str) -> bool:
    """Attach a Google sub to an existing user. Returns True on success."""
    if not user_id or not google_sub:
        return False
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET google_sub=? WHERE id=? AND google_sub IS NULL",
            (google_sub, user_id),
        )
        return (cur.rowcount or 0) > 0


# ===========================================================================
# Session CRUD (chat)
# ===========================================================================
def create_session(
    title: str = "New Chat",
    user_id: str = DEFAULT_USER_ID,
) -> str:
    sid = uuid.uuid4().hex
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, title, now, now, user_id),
        )
    return sid


def get_or_create_session(
    session_id: Optional[str] = None,
    user_id: str = DEFAULT_USER_ID,
) -> str:
    """Return an existing session id if valid, else create a fresh one."""
    if session_id:
        with _conn() as c:
            row = c.execute(
                "SELECT id FROM sessions WHERE id=? AND user_id=? LIMIT 1",
                (session_id, user_id),
            ).fetchone()
        if row:
            return session_id
    return create_session(user_id=user_id)


def list_sessions(user_id: str = DEFAULT_USER_ID) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, title, created_at, updated_at, user_id "
            "FROM sessions WHERE user_id=? "
            "ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_sessions(user_id: str = DEFAULT_USER_ID) -> int:
    """Per-user session count. For the global count use
    ``count_sessions_total()`` instead — this filters by user_id and
    will return 0 if called with ``user_id=None``."""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def session_exists(sid: str, user_id: str = DEFAULT_USER_ID) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? LIMIT 1",
            (sid, user_id),
        ).fetchone()
    return row is not None


def rename_session(
    sid: str,
    title: str,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET title=?, updated_at=? "
            "WHERE id=? AND user_id=?",
            (title, time.time(), sid, user_id),
        )


def session_image_ids(sid: str, user_id: str = DEFAULT_USER_ID) -> list[str]:
    """Return every distinct ``image_id`` referenced in a session's messages.

    Used by the delete-session path to unlink on-disk image files that
    were saved during ``/query/image``.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT m.metadata_json FROM messages m "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE m.session_id=? AND s.user_id=?",
            (sid, user_id),
        ).fetchall()
    ids: list[str] = []
    seen: set[str] = set()
    for r in rows:
        try:
            md = json.loads(r["metadata_json"] or "{}")
        except (TypeError, ValueError):
            continue
        img_id = md.get("image_id")
        if isinstance(img_id, str) and img_id and img_id not in seen:
            seen.add(img_id)
            ids.append(img_id)
    return ids


def delete_session(sid: str, user_id: str = DEFAULT_USER_ID) -> None:
    with _conn() as c:
        owned = c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? LIMIT 1",
            (sid, user_id),
        ).fetchone()
        if not owned:
            return
        c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        c.execute(
            "DELETE FROM sessions WHERE id=? AND user_id=?",
            (sid, user_id),
        )
        c.execute(
            "DELETE FROM session_summaries WHERE session_id=? AND user_id=?",
            (sid, user_id),
        )


def auto_title_session(
    sid: str,
    first_user_msg: str,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    title = first_user_msg.strip().replace("\n", " ")[:50]
    if len(first_user_msg) > 50:
        title += "…"
    rename_session(sid, title or "New Chat", user_id=user_id)


# ===========================================================================
# Messages
# ===========================================================================
def add_message(
    sid: str,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
    user_id: str = DEFAULT_USER_ID,
) -> int:
    now = time.time()
    with _conn() as c:
        owned = c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? LIMIT 1",
            (sid, user_id),
        ).fetchone()
        if not owned:
            return 0
        cur = c.execute(
            "INSERT INTO messages "
            "(session_id, role, content, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, role, content, json.dumps(metadata or {}), now),
        )
        c.execute(
            "UPDATE sessions SET updated_at=? WHERE id=? AND user_id=?",
            (now, sid, user_id),
        )
        return cur.lastrowid or 0


def get_messages(sid: str, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT m.id, m.role, m.content, m.metadata_json, m.created_at "
            "FROM messages m "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE m.session_id=? AND s.user_id=? "
            "ORDER BY m.created_at ASC, m.id ASC",
            (sid, user_id),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        out.append(d)
    return out


def delete_last_exchange(sid: str, user_id: str = DEFAULT_USER_ID) -> None:
    with _conn() as c:
        owned = c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? LIMIT 1",
            (sid, user_id),
        ).fetchone()
        if not owned:
            return
        rows = c.execute(
            "SELECT id, role FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT 2",
            (sid,),
        ).fetchall()
        if (
            len(rows) == 2
            and rows[0]["role"] == "assistant"
            and rows[1]["role"] == "user"
        ):
            c.execute(
                "DELETE FROM messages WHERE id IN (?, ?)",
                (rows[0]["id"], rows[1]["id"]),
            )


def delete_last_assistant_message(
    sid: str,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[str]:
    with _conn() as c:
        owned = c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? LIMIT 1",
            (sid, user_id),
        ).fetchone()
        if not owned:
            return None
        rows = c.execute(
            "SELECT id, role, content FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT 2",
            (sid,),
        ).fetchall()
        if len(rows) < 2:
            return None
        last = rows[0]
        prev = rows[1]
        if last["role"] != "assistant" or prev["role"] != "user":
            return None
        c.execute("DELETE FROM messages WHERE id=?", (last["id"],))
        return prev["content"]


# ===========================================================================
# Feedback
# ===========================================================================
def set_feedback(
    message_id: int,
    rating: str,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    with _conn() as c:
        owned = c.execute(
            "SELECT 1 FROM messages m "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE m.id=? AND s.user_id=? LIMIT 1",
            (message_id, user_id),
        ).fetchone()
        if not owned:
            return
        c.execute(
            "INSERT OR REPLACE INTO feedback "
            "(message_id, rating, created_at) VALUES (?, ?, ?)",
            (message_id, rating, time.time()),
        )


def get_feedback(
    message_id: int,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[str]:
    with _conn() as c:
        row = c.execute(
            "SELECT f.rating FROM feedback f "
            "JOIN messages m ON m.id = f.message_id "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE f.message_id=? AND s.user_id=?",
            (message_id, user_id),
        ).fetchone()
    return row["rating"] if row else None


# ===========================================================================
# Session summaries — for cross-session history
# ===========================================================================
def save_summary(
    session_id: str,
    summary: str,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    """Store (or replace) the summary for a session.

    Only the owner of the session may write a summary for it.
    """
    with _conn() as c:
        owned = c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? LIMIT 1",
            (session_id, user_id),
        ).fetchone()
        if not owned:
            return
        c.execute(
            "INSERT OR REPLACE INTO session_summaries "
            "(session_id, summary, created_at, user_id) VALUES (?, ?, ?, ?)",
            (session_id, summary, time.time(), user_id),
        )


def get_summary(
    session_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[str]:
    """Return the stored summary for a session, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT summary FROM session_summaries "
            "WHERE session_id=? AND user_id=? LIMIT 1",
            (session_id, user_id),
        ).fetchone()
    return row["summary"] if row else None


def list_recent_summaries(
    user_id: str = DEFAULT_USER_ID,
    limit: int = 3,
    exclude_session_id: Optional[str] = None,
) -> list[dict]:
    """Return the most recent N session summaries for a user.

    ``exclude_session_id`` lets the caller skip the current session so a
    query made *inside* a session doesn't see its own summary as "past".
    """
    with _conn() as c:
        if exclude_session_id:
            rows = c.execute(
                "SELECT session_id, summary, created_at "
                "FROM session_summaries "
                "WHERE user_id=? AND session_id != ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, exclude_session_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT session_id, summary, created_at "
                "FROM session_summaries "
                "WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


# ===========================================================================
# Document registry — used by the FastAPI surface
# ===========================================================================
@dataclass
class DocumentRow:
    """Lightweight record returned by the document CRUD functions."""

    document_id: str
    filename: str
    path: str
    status: str
    page_count: Optional[int]
    chunk_count: Optional[int]
    error: Optional[str]
    created_at: float
    updated_at: float
    user_id: str


def _row_to_document(r: sqlite3.Row) -> DocumentRow:
    return DocumentRow(
        document_id=r["document_id"],
        filename=r["filename"],
        path=r["path"],
        status=r["status"],
        page_count=r["page_count"],
        chunk_count=r["chunk_count"],
        error=r["error"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        user_id=r["user_id"],
    )


def create_document(
    *,
    filename: str,
    path: str,
    document_id: Optional[str] = None,
    status: str = "pending",
    user_id: str = DEFAULT_USER_ID,
) -> DocumentRow:
    """Insert a document row. Returns the new row."""
    doc_id = document_id or uuid.uuid4().hex
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO documents "
            "(document_id, filename, path, status, page_count, chunk_count, "
            " error, created_at, updated_at, user_id) "
            "VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
            (doc_id, filename, path, status, now, now, user_id),
        )
    return get_document(doc_id, user_id=user_id)  # type: ignore[return-value]


def update_document(
    document_id: str,
    *,
    status: Optional[str] = None,
    page_count: Optional[int] = None,
    chunk_count: Optional[int] = None,
    error: Optional[str] = None,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    """Patch fields on a document row. Only non-None args are written."""
    sets: list[str] = []
    params: list = []
    if status is not None:
        sets.append("status=?")
        params.append(status)
    if page_count is not None:
        sets.append("page_count=?")
        params.append(page_count)
    if chunk_count is not None:
        sets.append("chunk_count=?")
        params.append(chunk_count)
    if error is not None:
        sets.append("error=?")
        params.append(error)
    sets.append("updated_at=?")
    params.append(time.time())
    params.extend([document_id, user_id])
    sql = (
        f"UPDATE documents SET {', '.join(sets)} "
        f"WHERE document_id=? AND user_id=?"
    )
    with _conn() as c:
        c.execute(sql, params)


def list_documents(user_id: str = DEFAULT_USER_ID) -> list[DocumentRow]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM documents "
            "WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_document(
    document_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[DocumentRow]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM documents "
            "WHERE document_id=? AND user_id=? LIMIT 1",
            (document_id, user_id),
        ).fetchone()
    return _row_to_document(row) if row else None


def delete_document(
    document_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> bool:
    """Delete a document row. Returns True if a row was removed.

    Note: this does NOT touch ``query_metrics``. The metrics belong to
    the query that produced them, not the document that was cited.
    """
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM documents WHERE document_id=? AND user_id=?",
            (document_id, user_id),
        )
        return (cur.rowcount or 0) > 0


def sessions_referencing_document(
    filename: str,
    document_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> list[str]:
    """Return session ids where any message cites the given document.

    Matches on either ``filename`` or ``document_id`` inside the message
    metadata JSON. Both are stored in every persisted citation, so
    matching on both is more robust against filename case changes.

    Returns an empty list when nothing matches — the caller decides
    whether that is an error or simply "no conversations used this doc".
    """
    filename_pattern = f'%"filename": "{filename}"%'
    document_id_pattern = f'%"document_id": "{document_id}"%'
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT m.session_id FROM messages m "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE s.user_id = ? "
            "  AND (m.metadata_json LIKE ? OR m.metadata_json LIKE ?)",
            (user_id, filename_pattern, document_id_pattern),
        ).fetchall()
    return [r["session_id"] for r in rows]


# ===========================================================================
# Chat exports (preserved)
# ===========================================================================
def export_session_markdown(
    sid: str,
    user_id: str = DEFAULT_USER_ID,
) -> str:
    sessions = list_sessions(user_id=user_id)
    title = next((s["title"] for s in sessions if s["id"] == sid), None)
    if title is None:
        return ""
    msgs = get_messages(sid, user_id=user_id)

    lines: list[str] = [
        f"# {title}",
        "",
        f"_Exported from Argus on {time.strftime('%Y-%m-%d %H:%M')}_",
        "",
        "---",
        "",
    ]
    for m in msgs:
        role = "**You**" if m["role"] == "user" else "**Argus**"
        lines.append(f"### {role}")
        lines.append("")

        meta = m.get("metadata", {}) or {}
        if meta.get("image_upload") and meta.get("image_url"):
            lines.append(f"![uploaded image]({meta['image_url']})")
            lines.append("")
            lines.append(m["content"])
            lines.append("")
        else:
            lines.append(m["content"])
            lines.append("")

        srcs = meta.get("sources") or []
        if m["role"] == "assistant" and srcs:
            lines.append("**Sources:**")
            for s in srcs:
                lines.append(
                    f"- {s.get('source', '?')} — p.{s.get('page', '?')}"
                )
            lines.append("")

        trace = meta.get("trace") or []
        if m["role"] == "assistant" and trace:
            lines.append("<details><summary>Agent Reasoning</summary>")
            lines.append("")
            for step in trace:
                lines.append(
                    f"- `{step.get('state', '').upper()}` — "
                    f"{step.get('summary', '')}"
                )
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def export_session_pdf(
    sid: str,
    user_id: str = DEFAULT_USER_ID,
) -> bytes:
    sessions = list_sessions(user_id=user_id)
    title = next((s["title"] for s in sessions if s["id"] == sid), None)
    if title is None:
        return b""
    msgs = get_messages(sid, user_id=user_id)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=title,
        author="Argus",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ArgusTitle",
        parent=styles["Title"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#5B21B6"),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "ArgusMeta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#6B7280"),
        spaceAfter=20,
    )
    role_user = ParagraphStyle(
        "ArgusUserRole",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=colors.HexColor("#7C3AED"),
        spaceBefore=14,
        spaceAfter=6,
    )
    role_assistant = ParagraphStyle(
        "ArgusAssistantRole",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=colors.HexColor("#DB2777"),
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ArgusBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "ArgusSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=3,
    )

    def _esc(text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    story = []
    story.append(Paragraph(_esc(title), title_style))
    story.append(
        Paragraph(
            f"Exported from Argus on {time.strftime('%Y-%m-%d %H:%M')} · "
            f"{len(msgs)} messages",
            meta_style,
        )
    )
    for m in msgs:
        is_user = m["role"] == "user"
        role_label = "You" if is_user else "Argus"
        role_style = role_user if is_user else role_assistant
        story.append(Paragraph(role_label, role_style))
        for para in m["content"].split("\n\n"):
            para = para.strip()
            if not para:
                continue
            story.append(
                Paragraph(
                    _esc(para).replace("\n", "<br/>"), body_style
                )
            )
        if not is_user:
            srcs = m.get("metadata", {}).get("sources") or []
            if srcs:
                story.append(Paragraph("<b>Sources</b>", small_style))
                for s in srcs:
                    story.append(
                        Paragraph(
                            f"• {_esc(s.get('source', '?'))} — "
                            f"page {_esc(str(s.get('page', '?')))}",
                            small_style,
                        )
                    )
            trace = m.get("metadata", {}).get("trace") or []
            if trace:
                story.append(Spacer(1, 4))
                story.append(
                    Paragraph("<b>Agent Reasoning</b>", small_style)
                )
                for step in trace:
                    story.append(
                        Paragraph(
                            f"[{_esc(str(step.get('state', '')).upper())}] "
                            f"{_esc(step.get('summary', ''))}",
                            small_style,
                        )
                    )
        story.append(Spacer(1, 10))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ===========================================================================
# Janitor
# ===========================================================================
def delete_empty_sessions(
    max_age_seconds: float = 300,
    user_id: Optional[str] = None,
) -> int:
    cutoff = time.time() - max_age_seconds
    with _conn() as c:
        if user_id is None:
            rows = c.execute(
                """
                SELECT s.id
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.created_at < ?
                GROUP BY s.id
                HAVING COUNT(m.id) = 0
                """,
                (cutoff,),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT s.id
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.created_at < ? AND s.user_id = ?
                GROUP BY s.id
                HAVING COUNT(m.id) = 0
                """,
                (cutoff, user_id),
            ).fetchall()
        ids = [r["id"] for r in rows]
        for sid in ids:
            c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
            c.execute(
                "DELETE FROM session_summaries WHERE session_id=?", (sid,)
            )
        return len(ids)


__all__ = [
    "DEFAULT_USER_ID",
    "DATA_DIR",
    "DB_PATH",
    "CHROMA_DIR",
    "DocumentRow",
    "init_db",
    "backfill_user_id",
    "get_storage",
    # users
    "create_user",
    "get_user_by_email",
    "get_user_by_id",
    "migrate_anon_data_to_user",
    # admin
    "is_admin",
    "set_admin",
    "get_admin_by_email",
    # auth events
    "record_auth_event",
    # analytics
    "count_users",
    "count_documents_total",
    "count_messages_total",
    "count_sessions_total",
    "auth_events_by_day",
    "sessions_by_day",
    "record_query_metric",
    "rag_metrics_aggregate",
    "recent_queries",
    # password resets
    "create_password_reset",
    "consume_password_reset",
    "update_user_password",
    "purge_expired_password_resets",
    # google oauth
    "get_user_by_google_sub",
    "create_google_user",
    "link_google_sub",
    # chat
    "create_session",
    "get_or_create_session",
    "list_sessions",
    "count_sessions",
    "session_exists",
    "rename_session",
    "delete_session",
    "session_image_ids",
    "auto_title_session",
    "add_message",
    "get_messages",
    "delete_last_exchange",
    "delete_last_assistant_message",
    "set_feedback",
    "get_feedback",
    "export_session_markdown",
    "export_session_pdf",
    "delete_empty_sessions",
    # summaries
    "save_summary",
    "get_summary",
    "list_recent_summaries",
    # documents
    "create_document",
    "update_document",
    "list_documents",
    "get_document",
    "delete_document",
    "sessions_referencing_document",
]