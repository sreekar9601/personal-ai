"""Session memory: durable conversation history + full-text search.

Three stores in one SQLite file:
  - `sessions`: the serialized Pydantic AI message history per session, so a
    conversation survives restarts and can be resumed.
  - `messages_fts`: an FTS5 index of plain-text turns for "what did we say
    about X" search across past conversations.
  - `pending_approvals`: turns paused on a Telegram Approve/Deny button, so an
    approval survives a process restart (PLAN.md §2.3).

Durable *facts* (USER.md / MEMORY.md) are plain markdown read at prompt-assembly
time; see read_user() / read_memory().
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)

from . import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.SESSION_DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                   session_id TEXT PRIMARY KEY,
                   history    BLOB NOT NULL,
                   updated_at TEXT NOT NULL
               )"""
        )
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
               USING fts5(session_id, ts, role, text)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pending_approvals (
                   token      TEXT PRIMARY KEY,
                   session_id TEXT NOT NULL,
                   tier       TEXT NOT NULL,
                   call_ids   TEXT NOT NULL,
                   history    BLOB NOT NULL,
                   created_at TEXT NOT NULL
               )"""
        )


def _trim_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Bound history growth (PLAN.md §2.4): keep the most recent window.

    The cut must land on a ModelRequest that carries a user prompt — cutting
    mid tool-call cycle would hand the provider an orphaned tool result. If no
    clean boundary exists inside the window, return the history unchanged
    (correctness beats the bound).
    """
    limit = config.HISTORY_MAX_MESSAGES
    if limit <= 0 or len(messages) <= limit:
        return messages
    window = messages[-limit:]
    for i, msg in enumerate(window):
        if isinstance(msg, ModelRequest) and any(
            isinstance(p, UserPromptPart) for p in msg.parts
        ):
            return window[i:]
    return messages


def load_history(session_id: str) -> list[ModelMessage]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT history FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return []
    return _trim_history(list(ModelMessagesTypeAdapter.validate_json(row[0])))


def save_history(session_id: str, messages: list[ModelMessage]) -> None:
    blob = ModelMessagesTypeAdapter.dump_json(messages)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO sessions (session_id, history, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET history=excluded.history,
                                                     updated_at=excluded.updated_at""",
            (session_id, blob, now),
        )


def index_turn(session_id: str, role: str, text: str) -> None:
    """Add one plain-text turn to the FTS index (best-effort; never blocks a turn)."""
    if not text:
        return
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages_fts (session_id, ts, role, text) VALUES (?, ?, ?, ?)",
            (session_id, now, role, text),
        )


def search(query: str, limit: int = 10) -> list[dict]:
    """Full-text search across past turns. Returns most-relevant snippets."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT session_id, ts, role, text
               FROM messages_fts WHERE messages_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
    return [
        {"session_id": r[0], "ts": r[1], "role": r[2], "text": r[3]} for r in rows
    ]


def _read(path) -> str:
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return ""


def read_user() -> str:
    return _read(config.USER_MD)


def read_memory() -> str:
    return _read(config.MEMORY_MD)


# --- Pending approvals (survive restarts) -------------------------------------
_APPROVAL_TTL = timedelta(hours=24)


def save_pending(
    token: str,
    session_id: str,
    tier: str,
    call_ids: list[str],
    messages: list[ModelMessage],
) -> None:
    """Persist a turn that is paused on a Telegram Approve/Deny decision."""
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        conn.execute(
            "DELETE FROM pending_approvals WHERE created_at < ?",
            ((now - _APPROVAL_TTL).isoformat(),),
        )
        conn.execute(
            """INSERT OR REPLACE INTO pending_approvals
               (token, session_id, tier, call_ids, history, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                token,
                session_id,
                tier,
                json.dumps(call_ids),
                ModelMessagesTypeAdapter.dump_json(messages),
                now.isoformat(),
            ),
        )


def pop_pending(token: str) -> tuple[str, list[ModelMessage], str, list[str]] | None:
    """Fetch-and-delete a pending approval. Returns
    (session_id, resume_messages, tier, call_ids) or None if expired/unknown."""
    cutoff = (datetime.now(timezone.utc) - _APPROVAL_TTL).isoformat()
    with _connect() as conn:
        row = conn.execute(
            """SELECT session_id, tier, call_ids, history, created_at
               FROM pending_approvals WHERE token = ?""",
            (token,),
        ).fetchone()
        conn.execute("DELETE FROM pending_approvals WHERE token = ?", (token,))
    if not row or row[4] < cutoff:
        return None
    messages = list(ModelMessagesTypeAdapter.validate_json(row[3]))
    return row[0], messages, row[1], json.loads(row[2])


# --- Durable facts (the active memory layer) ---------------------------------
# Phase 0 only *read* MEMORY.md. Phase 1 lets the agent grow it: when it learns
# a stable fact about the user (during chat or wiki synthesis) it records one
# line here, which then rides in the system prefix of every future turn.
_PLACEHOLDER = "- (no durable facts yet)"


def add_fact(fact: str) -> str:
    """Append a one-line durable fact to memory/MEMORY.md (idempotent-ish).

    Strips the seed placeholder on first real fact, normalises to a single
    bullet, and skips exact duplicates so the layer doesn't bloat over time.
    """
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; memory writes are disabled."
    fact = " ".join(fact.strip().lstrip("-").split())
    if not fact:
        return "[skipped] empty fact"

    path = config.MEMORY_MD
    existing = path.read_text() if path.exists() else ""
    lines = existing.splitlines()
    bullets = {ln.strip().lstrip("-").strip() for ln in lines if ln.strip().startswith("-")}
    if fact in bullets:
        return f"[known] already recorded: {fact}"

    kept = [ln for ln in lines if ln.strip() != _PLACEHOLDER]
    body = "\n".join(kept).rstrip()
    body = (body + "\n" if body else "") + f"- {fact}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return f"[remembered] {fact}"
