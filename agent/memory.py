"""Session memory: durable conversation history + full-text search.

Two stores in one SQLite file:
  - `sessions`: the serialized Pydantic AI message history per session, so a
    conversation survives restarts and can be resumed.
  - `messages_fts`: an FTS5 index of plain-text turns for "what did we say
    about X" search across past conversations.

Durable *facts* (USER.md / MEMORY.md) are plain markdown read at prompt-assembly
time; see read_user() / read_memory().
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

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


def load_history(session_id: str) -> list[ModelMessage]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT history FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return []
    return list(ModelMessagesTypeAdapter.validate_json(row[0]))


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
