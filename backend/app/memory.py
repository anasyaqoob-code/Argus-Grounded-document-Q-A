"""Chat memory: formatting + persistence bridge.

The lazy ``from . import storage`` calls inside ``ChatSession.add`` /
``new_session`` / ``load_session`` keep this module importable even when
``storage`` cannot be imported (e.g. a broken DB path in a fresh deploy).
``format_history_for_prompt`` is pure and never touches storage, which is
what lets ``rag_engine`` import this module unconditionally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import ChatMessage
from .storage import DEFAULT_USER_ID


# ---------------------------------------------------------------------------
# Session view
# ---------------------------------------------------------------------------
@dataclass
class ChatSession:
    """Lightweight in-memory view over a persisted session.

    ``user_id`` scopes the session to a caller. Defaults to
    ``storage.DEFAULT_USER_ID`` ("anon") for single-user deployments.
    """

    id: str
    title: str = "New Chat"
    messages: list[ChatMessage] = field(default_factory=list)
    user_id: str = DEFAULT_USER_ID

    def add(
        self,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> int:
        """Append to in-memory buffer AND persist. Returns the persisted
        message id (0 if the session isn't owned by ``self.user_id``)."""
        from . import storage  # lazy — keeps this module importable

        self.messages.append(
            ChatMessage(role=role, content=content)  # type: ignore[arg-type]
        )
        return storage.add_message(
            self.id,
            role,
            content,
            metadata=metadata,
            user_id=self.user_id,
        )


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------
def new_session(user_id: str = DEFAULT_USER_ID) -> ChatSession:
    from . import storage

    sid = storage.create_session(user_id=user_id)
    return ChatSession(id=sid, user_id=user_id)


def load_session(
    sid: str,
    user_id: str = DEFAULT_USER_ID,
) -> ChatSession:
    """Rebuild a ChatSession from disk, scoped to ``user_id``.

    If the session does not belong to ``user_id``, returns an empty
    ChatSession with a placeholder title — never leaks another user's
    history.
    """
    from . import storage

    rows = storage.list_sessions(user_id=user_id)
    title = next((r["title"] for r in rows if r["id"] == sid), None)
    if title is None:
        return ChatSession(id=sid, title="Chat", user_id=user_id)

    msgs = [
        ChatMessage(role=m["role"], content=m["content"])  # type: ignore[arg-type]
        for m in storage.get_messages(sid, user_id=user_id)
    ]
    return ChatSession(id=sid, title=title, messages=msgs, user_id=user_id)


# ---------------------------------------------------------------------------
# Prompt formatting (pure — no storage dependency)
# ---------------------------------------------------------------------------
def format_history_for_prompt(history: list[ChatMessage], limit: int) -> str:
    """Render last ``limit`` messages as plain text for LLM prompts."""
    if not history:
        return "(no prior conversation)"
    recent = history[-limit:] if limit > 0 else history
    lines = []
    for msg in recent:
        tag = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{tag}: {msg.content}")
    return "\n".join(lines)


__all__ = [
    "ChatSession",
    "new_session",
    "load_session",
    "format_history_for_prompt",
]