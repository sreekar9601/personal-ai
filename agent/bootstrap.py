"""Startup preparation: fail-closed checks + the persistent-volume layout.

Runs once at process start, before any handler is registered (PLAN.md §9.2):

  1. Access control fails CLOSED: an empty Telegram allowlist aborts startup
     unless DEV_MODE=true is set explicitly.
  2. Deployed mode (PERSONAL_AI_DATA set): verify the volume is actually
     mounted, install the git deploy key, clone the knowledge repo on first
     boot (pull on later boots), and give git an identity so the agent's
     knowledge commits succeed unattended.

Local dev (no PERSONAL_AI_DATA) only runs the access-control check; the
working copy is already the knowledge repo.
"""
from __future__ import annotations

import logging
import os
import subprocess

from . import config

log = logging.getLogger("personal-ai.bootstrap")

_GIT_IDENTITY_NAME = "personal-ai"
_GIT_IDENTITY_EMAIL = "personal-ai@localhost"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=config.REPO_ROOT, capture_output=True, text=True
    )


def ensure_environment() -> None:
    """Prepare the runtime environment or exit loudly. Call before build_app wiring."""
    _check_access_control()
    if config.DEPLOYED:
        _ensure_volume()
        _ensure_git_auth()
        _ensure_repo()
        _ensure_git_identity()


def _check_access_control() -> None:
    if not config.TELEGRAM_ALLOWED_USER_IDS and not config.DEV_MODE:
        raise SystemExit(
            "TELEGRAM_ALLOWED_USER_IDS is empty — the bot would be open to anyone"
            " on Telegram. Set your numeric id (from @userinfobot), or set"
            " DEV_MODE=true to run open deliberately (dev only)."
        )
    if config.DEV_MODE and not config.TELEGRAM_ALLOWED_USER_IDS:
        log.warning("DEV_MODE: running with an EMPTY allowlist — bot is open.")


def _ensure_volume() -> None:
    if not config.DATA_ROOT.is_dir():
        raise SystemExit(
            f"PERSONAL_AI_DATA={config.DATA_ROOT} does not exist. The persistent"
            " volume is not mounted; refusing to boot on ephemeral storage"
            " (all data would be lost on redeploy)."
        )
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_git_auth() -> None:
    """Install the deploy key (if provided) for clone/pull/push over SSH."""
    if not config.GIT_SSH_KEY:
        return
    key_path = config.DATA_ROOT / "deploy_key"
    key = config.GIT_SSH_KEY
    key_path.write_text(key if key.endswith("\n") else key + "\n")
    key_path.chmod(0o600)
    os.environ["GIT_SSH_COMMAND"] = (
        f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new"
    )


def _ensure_repo() -> None:
    """First boot: clone the knowledge repo onto the volume. Later boots: pull."""
    if (config.REPO_ROOT / ".git").is_dir():
        res = _git("pull", "--ff-only")
        if res.returncode != 0:
            # Never block startup on a pull (offline remote, diverged history);
            # the local clone is authoritative until push/pull succeeds again.
            log.warning("git pull failed (continuing with local clone): %s",
                        (res.stderr or res.stdout).strip())
        return
    if not config.GIT_REMOTE_URL:
        raise SystemExit(
            f"No knowledge repo at {config.REPO_ROOT} and GIT_REMOTE_URL is not"
            " set — cannot clone on first boot. Set GIT_REMOTE_URL (and"
            " GIT_SSH_KEY for a private repo)."
        )
    log.info("First boot: cloning %s -> %s", config.GIT_REMOTE_URL, config.REPO_ROOT)
    res = subprocess.run(
        ["git", "clone", config.GIT_REMOTE_URL, str(config.REPO_ROOT)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise SystemExit(f"git clone failed: {(res.stderr or res.stdout).strip()}")


def _ensure_git_identity() -> None:
    """Commits need an identity; set a repo-local one so they work unattended."""
    if not _git("config", "user.email").stdout.strip():
        _git("config", "user.name", _GIT_IDENTITY_NAME)
        _git("config", "user.email", _GIT_IDENTITY_EMAIL)
