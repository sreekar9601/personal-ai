"""Git is the single sync authority. After a successful turn we stage the
tracked knowledge dirs, commit, and (optionally) push.

Commits are the audit trail alongside vault/log.md. Push is best-effort and
disabled by the kill switch.
"""
from __future__ import annotations

import subprocess

from . import config


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=config.REPO_ROOT,
        capture_output=True,
        text=True,
    )


def is_repo() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


def has_remote() -> bool:
    return bool(_git("remote").stdout.strip())


def commit_knowledge(message: str) -> str | None:
    """Stage tracked dirs and commit if anything changed. Returns commit subject
    on success, None if there was nothing to commit. Never raises."""
    if config.KILL_SWITCH or not is_repo():
        return None
    # Stage only the knowledge dirs that exist.
    for d in config.GIT_TRACKED_DIRS:
        if (config.REPO_ROOT / d).exists():
            _git("add", "--", d)
    # Anything staged?
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return None
    res = _git("commit", "-m", message)
    if res.returncode != 0:
        return None
    if config.GIT_PUSH and has_remote():
        _git("push")  # best-effort
    return message
