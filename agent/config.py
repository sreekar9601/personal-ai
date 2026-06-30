"""Central configuration: paths, env, and the write-approval allowlist.

Everything that the rest of the service needs to know about *where things live*
and *what is allowed* is resolved here, once, at import time.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = the directory that contains this `agent/` package.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the repo root (no-op if absent; real env still wins).
load_dotenv(REPO_ROOT / ".env")

# --- Filesystem layout -------------------------------------------------------
VAULT_DIR = REPO_ROOT / "vault"
MEMORY_DIR = REPO_ROOT / "memory"
SKILLS_DIR = REPO_ROOT / "skills"
PLAYBOOKS_DIR = REPO_ROOT / "playbooks"
FINANCE_DIR = REPO_ROOT / "finance"
AGENT_DIR = REPO_ROOT / "agent"
DATA_DIR = REPO_ROOT / ".data"  # local-only runtime state (sqlite); gitignored
DATA_DIR.mkdir(exist_ok=True)

AGENT_MD = REPO_ROOT / "AGENT.md"
USER_MD = MEMORY_DIR / "USER.md"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"
SESSION_DB = DATA_DIR / "sessions.db"

# --- Write-approval allowlist ------------------------------------------------
# Writes under these paths are auto-approved. Anything else triggers a
# human-in-the-loop approval (see agent/hooks.py). Channel-1 self-improvement
# (skills/playbooks) lives inside this list; agent/ code does NOT (PR-gated).
AUTO_APPROVE_WRITE_DIRS = [
    VAULT_DIR,
    SKILLS_DIR,
    PLAYBOOKS_DIR,
    MEMORY_DIR,
    FINANCE_DIR / "transactions",
]

# Dirs that get staged + committed to git after each successful turn.
GIT_TRACKED_DIRS = ["vault", "skills", "playbooks", "memory", "finance/transactions"]


# --- Environment -------------------------------------------------------------
def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
# Comma-separated list of Telegram numeric user IDs allowed to talk to the bot.
TELEGRAM_ALLOWED_USER_IDS = {
    int(x) for x in (_env("TELEGRAM_ALLOWED_USER_IDS", "") or "").replace(" ", "").split(",") if x
}

ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
GEMINI_API_KEY = _env("GEMINI_API_KEY")

# Kill switch: when truthy, every side-effectful tool (vault write, git push)
# is disabled. One flag, whole blast radius.
KILL_SWITCH = (_env("KILL_SWITCH", "") or "").lower() in {"1", "true", "yes", "on"}

# Ceiling on model requests per turn so a runaway tool loop cannot burn budget.
MAX_TURNS = int(_env("MAX_TURNS", "12"))

# Push to git remote after committing (best-effort; needs an 'origin' remote).
GIT_PUSH = (_env("GIT_PUSH", "false") or "").lower() in {"1", "true", "yes", "on"}

# --- Proactive scheduling (Phase 4) -----------------------------------------
# When enabled, the agent runs unattended jobs: a nightly wiki-synthesis pass and
# a morning briefing pushed to you on Telegram. Disabled if there's no chat to
# message. Times are local-hour ints; minutes are nudged off :00 to spread load.
PROACTIVE_ENABLED = (_env("PROACTIVE_ENABLED", "true") or "").lower() in {"1", "true", "yes", "on"}
SYNTHESIS_HOUR = int(_env("SYNTHESIS_HOUR", "3"))   # nightly inbox -> wiki
BRIEFING_HOUR = int(_env("BRIEFING_HOUR", "8"))     # morning briefing
# Chat to push proactive messages to. Defaults to the (single) allowed user id —
# in a private chat the chat id equals the user id.
_chat = _env("TELEGRAM_CHAT_ID")
TELEGRAM_CHAT_ID = (
    int(_chat) if _chat
    else (sorted(TELEGRAM_ALLOWED_USER_IDS)[0] if TELEGRAM_ALLOWED_USER_IDS else None)
)
