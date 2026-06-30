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

import re
from pathlib import Path

from . import config

# --- Content guards (Phase 6) ------------------------------------------------
# A hard ceiling on a single write: a personal note is never this big, so a
# larger write is a runaway loop or abuse, not a real note.
MAX_WRITE_BYTES = 256 * 1024
# Private-key material must never be written into the knowledge repo, even inside
# the auto-approve zone. High-precision pattern, so false positives are unlikely.
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


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


def assess_content(content: str) -> str | None:
    """Deterministic content gate, applied to every write regardless of path.

    Returns a refusal reason, or None if the content is allowed. This is the
    deterministic half of the dangerous-action gate the module promised; a
    cheap-tier LLM classifier can be layered in front of it later for fuzzier
    risks, but these two rules are high-precision and need no model call.
    """
    if len(content.encode("utf-8", "ignore")) > MAX_WRITE_BYTES:
        return f"write exceeds {MAX_WRITE_BYTES // 1024} KiB cap (likely a runaway loop)."
    if _PRIVATE_KEY_RE.search(content):
        return "content contains private-key material, which is never written to the repo."
    return None
