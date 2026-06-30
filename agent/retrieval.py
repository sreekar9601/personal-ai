"""Keyword retrieval over the knowledge vault (Phase 1).

Phase 0 indexed *conversation* turns (see agent/memory.py:messages_fts). This is
the other half: an FTS5 index over the markdown *content* of the vault so the
agent can answer "what do I know about X" by retrieving real notes and wiki
pages instead of guessing from the prompt.

Design notes:
  - One FTS5 table (`vault_fts`) living in the same SQLite file as session
    memory. Rows are (path, title, body); `path` is UNINDEXED so it is stored
    and returned but never pollutes ranking.
  - The index is a derived cache of files on disk, not a source of truth. We
    rebuild it from scratch on startup (cheap at personal scale) and keep it
    fresh incrementally as the agent writes/moves files.
  - User queries are free text, not FTS5 syntax, so we sanitise them into a
    prefix-OR query and never let a stray quote/operator raise.
"""
from __future__ import annotations

import re
import sqlite3

from . import config

# Files we index: markdown under vault/, excluding the structural log/index churn
# is *not* excluded — the log and index are legitimately searchable knowledge.
_MIN_INDEXABLE_CHARS = 1  # skip truly empty files (e.g. .gitkeep has none)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.SESSION_DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts
               USING fts5(path UNINDEXED, title, body)"""
        )


# --- Title extraction --------------------------------------------------------
def _title_for(rel_path: str, body: str) -> str:
    """First markdown heading, else the humanised filename stem."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or rel_path
    stem = rel_path.rsplit("/", 1)[-1].removesuffix(".md")
    return stem.replace("-", " ").replace("_", " ").strip() or rel_path


# --- Incremental maintenance -------------------------------------------------
def _is_vault_md(rel_path: str) -> bool:
    return rel_path.endswith(".md") and rel_path.replace("\\", "/").startswith("vault/")


def index_file(rel_path: str) -> None:
    """Re-index a single vault markdown file. Best-effort; never raises.

    Called after every successful vault write so retrieval stays in sync with
    what the agent just wrote. A no-op for non-vault or non-markdown paths.
    """
    try:
        rel_path = rel_path.replace("\\", "/")
        if not _is_vault_md(rel_path):
            return
        abs_path = (config.REPO_ROOT / rel_path).resolve()
        with _connect() as conn:
            conn.execute("DELETE FROM vault_fts WHERE path = ?", (rel_path,))
            if not abs_path.is_file():
                return
            body = abs_path.read_text()
            if len(body.strip()) < _MIN_INDEXABLE_CHARS:
                return
            conn.execute(
                "INSERT INTO vault_fts (path, title, body) VALUES (?, ?, ?)",
                (rel_path, _title_for(rel_path, body), body),
            )
    except Exception:  # pragma: no cover - indexing must never break a turn
        pass


def remove_file(rel_path: str) -> None:
    """Drop a file from the index (e.g. after it is archived/moved)."""
    try:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM vault_fts WHERE path = ?", (rel_path.replace("\\", "/"),)
            )
    except Exception:  # pragma: no cover
        pass


def reindex_vault() -> int:
    """Rebuild the whole vault index from disk. Returns the number of files indexed."""
    rows: list[tuple[str, str, str]] = []
    for path in sorted(config.VAULT_DIR.rglob("*.md")):
        body = path.read_text()
        if len(body.strip()) < _MIN_INDEXABLE_CHARS:
            continue
        rel = path.resolve().relative_to(config.REPO_ROOT).as_posix()
        rows.append((rel, _title_for(rel, body), body))
    with _connect() as conn:
        conn.execute("DELETE FROM vault_fts")
        conn.executemany(
            "INSERT INTO vault_fts (path, title, body) VALUES (?, ?, ?)", rows
        )
    return len(rows)


# --- Query -------------------------------------------------------------------
def _fts_query(raw: str) -> str | None:
    """Turn free-text into a safe FTS5 prefix-OR query.

    Each word becomes a prefix term (`word*`) and terms are OR-ed for recall;
    bm25 rank then surfaces the densest matches first. Returns None if the query
    has no usable tokens (caller treats that as "no matches").
    """
    tokens = re.findall(r"\w+", raw.lower())
    if not tokens:
        return None
    return " OR ".join(f"{t}*" for t in tokens)


def search_vault(query: str, limit: int = 8) -> list[dict]:
    """Keyword search the vault. Returns [{path, title, snippet}] best-first."""
    match = _fts_query(query)
    if not match:
        return []
    with _connect() as conn:
        try:
            rows = conn.execute(
                """SELECT path, title,
                          snippet(vault_fts, 2, '«', '»', ' … ', 12) AS snip
                   FROM vault_fts
                   WHERE vault_fts MATCH ?
                   ORDER BY bm25(vault_fts) LIMIT ?""",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{"path": r[0], "title": r[1], "snippet": r[2]} for r in rows]
