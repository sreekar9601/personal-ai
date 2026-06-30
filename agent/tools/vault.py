"""Filesystem tools scoped to the knowledge repo.

These are *our* tools, not a runtime builtin — so the security model is precise:
reads are confined to the repo, writes go through the approval gate in
agent.hooks, and the kill switch disables writes entirely.

The functions here are pure helpers. The agent-facing tools (with RunContext and
approval semantics) are registered in agent/loop.py and call into these.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..hooks import assess_content, resolve_in_repo


def read_vault(rel_path: str) -> str:
    """Read a UTF-8 text file by repo-relative path (e.g. 'vault/index.md')."""
    path = resolve_in_repo(rel_path)
    if not path.exists():
        return f"[not found] {rel_path}"
    if path.is_dir():
        return _list_dir(path)
    return path.read_text()


def _list_dir(path: Path) -> str:
    rel = path.relative_to(config.REPO_ROOT)
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
    return f"[dir] {rel}/\n" + "\n".join(entries)


def list_vault(rel_path: str = "vault") -> str:
    """List a directory's contents by repo-relative path."""
    path = resolve_in_repo(rel_path)
    if not path.exists():
        return f"[not found] {rel_path}"
    return _list_dir(path) if path.is_dir() else read_vault(rel_path)


def write_vault(rel_path: str, content: str) -> str:
    """Write text to a repo-relative path, creating parent dirs. Kill-switch aware.

    Caller (loop.py) is responsible for the approval gate before calling this.
    """
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; writes are disabled."
    refusal = assess_content(content)
    if refusal:
        return f"[refused] {refusal}"
    path = resolve_in_repo(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"[written] {rel_path} ({len(content)} chars)"


def append_vault(rel_path: str, content: str) -> str:
    """Append text to a repo-relative path (used for logs like vault/log.md)."""
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; writes are disabled."
    refusal = assess_content(content)
    if refusal:
        return f"[refused] {refusal}"
    path = resolve_in_repo(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    return f"[appended] {rel_path}"


def move_vault(src_rel: str, dst_rel: str) -> str:
    """Move/rename a file within the repo (used by synthesis to archive captures).

    Both paths are confined to the repo; the approval gate (loop.py) governs the
    destination just like a write. Kill-switch aware.
    """
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; moves are disabled."
    src = resolve_in_repo(src_rel)
    dst = resolve_in_repo(dst_rel)
    if not src.exists():
        return f"[not found] {src_rel}"
    if src.is_dir():
        return f"[refused] {src_rel} is a directory; only files can be moved."
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return f"[moved] {src_rel} -> {dst_rel}"
