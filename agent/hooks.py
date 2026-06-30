"""Pre-execution gate for filesystem writes.

Two jobs:
  1. Path safety: resolve any agent-supplied path against the repo root and
     refuse anything that escapes it (no `../../etc/...`, no absolute paths out).
  2. Approval policy: decide whether a write is auto-approved (inside the
     allowlist) or must be confirmed by a human.

This is the deterministic half of the dangerous-command gate. A cheap-tier
classifier can be layered on later (Phase 6) for shell commands; for Phase 0 the
only side effect is a vault write, and a path allowlist fully covers it.
"""
from __future__ import annotations

from pathlib import Path

from . import config


class PathNotAllowed(Exception):
    """Raised when a path escapes the repo root entirely (hard refusal)."""


def resolve_in_repo(rel_path: str) -> Path:
    """Resolve `rel_path` (relative to repo root) and ensure it stays inside it."""
    candidate = (config.REPO_ROOT / rel_path).resolve()
    root = config.REPO_ROOT.resolve()
    if root != candidate and root not in candidate.parents:
        raise PathNotAllowed(
            f"Path {rel_path!r} resolves outside the repo and is refused."
        )
    return candidate


def is_auto_approved(abs_path: Path) -> bool:
    """True if a write to this absolute path needs no human confirmation."""
    abs_path = abs_path.resolve()
    for allowed in config.AUTO_APPROVE_WRITE_DIRS:
        allowed = allowed.resolve()
        if abs_path == allowed or allowed in abs_path.parents:
            return True
    return False
