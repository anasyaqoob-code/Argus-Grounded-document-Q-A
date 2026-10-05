"""Finding #7 (Medium): chat sessions and documents must be user-isolated.

Regression guard for:
"SQLite data is stored in one relative local database. In a multi-user
deployment, sessions can be globally visible unless the platform isolates
each process."

Fix: every session/message/document/feedback read and write in
``storage.py`` takes a ``user_id`` and filters on it. Every FastAPI route
reads ``X-User-Id`` (defaulting to ``anon``).

This file proves cross-user access is blocked for every resource type.
"""

from __future__ import annotations

import pytest

from app import storage


# --- sessions ---------------------------------------------------------
def test_sessions_are_user_scoped():
    storage.create_session(title="Alice's chat", user_id="alice")
    storage.create_session(title="Bob's chat", user_id="bob")

    alice_list = storage.list_sessions(user_id="alice")
    bob_list = storage.list_sessions(user_id="bob")

    alice_titles = {s["title"] for s in alice_list}
    bob_titles = {s["title"] for s in bob_list}

    assert "Alice's chat" in alice_titles
    assert "Bob's chat" not in alice_titles
    assert "Bob's chat" in bob_titles
    assert "Alice's chat" not in bob_titles


def test_cross_user_message_read_blocked():
    sid = storage.create_session(title="Alice only", user_id="alice")
    storage.add_message(sid, "user", "alice secret", user_id="alice")

    # Bob cannot read Alice's messages even with the correct session_id
    assert storage.get_messages(sid, user_id="bob") == []
    assert len(storage.get_messages(sid, user_id="alice")) == 1


def test_cross_user_write_blocked():
    sid = storage.create_session(title="Bob only", user_id="bob")
    # Alice tries to write into Bob's session
    rc = storage.add_message(sid, "user", "intrusion", user_id="alice")
    assert rc == 0, "cross-user write must be rejected"

    bob_msgs = storage.get_messages(sid, user_id="bob")
    assert all("intrusion" not in m["content"] for m in bob_msgs)


def test_cross_user_rename_blocked():
    sid = storage.create_session(title="Bob chat", user_id="bob")
    storage.rename_session(sid, "hacked", user_id="alice")

    bob_sessions = storage.list_sessions(user_id="bob")
    titles = {s["title"] for s in bob_sessions}
    assert "Bob chat" in titles
    assert "hacked" not in titles


def test_cross_user_delete_blocked():
    sid = storage.create_session(title="Bob chat", user_id="bob")
    storage.delete_session(sid, user_id="alice")

    assert storage.session_exists(sid, user_id="bob"), (
        "delete by wrong user must be a no-op"
    )


def test_get_or_create_session_respects_user():
    sid = storage.create_session(title="Alice", user_id="alice")
    # Bob asking for Alice's session id gets a NEW session
    bob_sid = storage.get_or_create_session(sid, user_id="bob")
    assert bob_sid != sid

    # But Alice gets her session back
    alice_sid = storage.get_or_create_session(sid, user_id="alice")
    assert alice_sid == sid


# --- documents --------------------------------------------------------
def test_documents_are_user_scoped():
    storage.create_document(
        filename="alice.pdf", path="/tmp/a.pdf",
        document_id="doc_alice", user_id="alice",
    )
    storage.create_document(
        filename="bob.pdf", path="/tmp/b.pdf",
        document_id="doc_bob", user_id="bob",
    )

    alice_docs = {d.document_id for d in storage.list_documents(user_id="alice")}
    bob_docs = {d.document_id for d in storage.list_documents(user_id="bob")}

    assert "doc_alice" in alice_docs
    assert "doc_bob" not in alice_docs
    assert "doc_bob" in bob_docs
    assert "doc_alice" not in bob_docs


def test_cross_user_document_read_blocked():
    storage.create_document(
        filename="alice.pdf", path="/tmp/a.pdf",
        document_id="doc_alice", user_id="alice",
    )
    assert storage.get_document("doc_alice", user_id="bob") is None
    assert storage.get_document("doc_alice", user_id="alice") is not None


def test_cross_user_document_delete_blocked():
    storage.create_document(
        filename="alice.pdf", path="/tmp/a.pdf",
        document_id="doc_alice", user_id="alice",
    )
    assert storage.delete_document("doc_alice", user_id="bob") is False
    assert storage.get_document("doc_alice", user_id="alice") is not None


# --- feedback ---------------------------------------------------------
def test_feedback_is_user_scoped():
    sid = storage.create_session(title="Alice", user_id="alice")
    mid = storage.add_message(sid, "assistant", "answer", user_id="alice")

    # Bob's write attempt is silently ignored
    storage.set_feedback(mid, "up", user_id="bob")
    assert storage.get_feedback(mid, user_id="bob") is None

    # Alice's write works
    storage.set_feedback(mid, "up", user_id="alice")
    assert storage.get_feedback(mid, user_id="alice") == "up"


# --- exports ----------------------------------------------------------
def test_export_respects_ownership():
    sid = storage.create_session(title="Alice export", user_id="alice")
    storage.add_message(sid, "user", "hello", user_id="alice")

    # Bob's export attempt returns empty
    assert storage.export_session_markdown(sid, user_id="bob") == ""
    assert storage.export_session_pdf(sid, user_id="bob") == b""

    # Alice's export works
    md = storage.export_session_markdown(sid, user_id="alice")
    assert "Alice export" in md
    pdf = storage.export_session_pdf(sid, user_id="alice")
    assert pdf[:4] == b"%PDF"
    