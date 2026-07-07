"""Central configuration: paths, env, and the write-approval allowlist.

Everything that the rest of the service needs to know about *where things live*
and *what is allowed* is resolved here, once, at import time.

Two layouts (PLAN.md §9):
  - Local dev: the working copy IS the knowledge repo; sqlite in `.data/`.
  - Deployed (PERSONAL_AI_DATA set, e.g. /data on the Fly volume): the code runs
    from the image, while the knowledge repo lives in a git clone at
    `$PERSONAL_AI_DATA/repo` and sqlite at `$PERSONAL_AI_DATA/state`, both on
    the persistent volume so they survive redeploys. agent/bootstrap.py
    prepares that layout at startup.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Where the *code* lives (the checkout/image this package runs from).
CODE_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the code root (no-op if absent; real env still wins).
load_dotenv(CODE_ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _flag(name: str, default: str = "") -> bool:
    return (_env(name, default) or "").lower() in {"1", "true", "yes", "on"}


# --- Filesystem layout -------------------------------------------------------
_DATA_ENV = _env("PERSONAL_AI_DATA")
DEPLOYED = bool(_DATA_ENV)

if DEPLOYED:
    DATA_ROOT = Path(_DATA_ENV)  # the persistent volume mount (e.g. /data)
    REPO_ROOT = DATA_ROOT / "repo"  # git clone of the knowledge repo
    DATA_DIR = DATA_ROOT / "state"  # sqlite lives here (created by bootstrap)
else:
    DATA_ROOT = CODE_ROOT
    REPO_ROOT = CODE_ROOT  # the working copy is the knowledge repo
    DATA_DIR = CODE_ROOT / ".data"  # local-only runtime state; gitignored
    DATA_DIR.mkdir(exist_ok=True)

VAULT_DIR = REPO_ROOT / "vault"
MEMORY_DIR = REPO_ROOT / "memory"
SKILLS_DIR = REPO_ROOT / "skills"
PLAYBOOKS_DIR = REPO_ROOT / "playbooks"
FINANCE_DIR = REPO_ROOT / "finance"
AGENT_DIR = REPO_ROOT / "agent"

WEB_DIR = CODE_ROOT / "web"  # the PWA's static shell ships with the code

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
KILL_SWITCH = _flag("KILL_SWITCH")

# Explicit opt-in to run with an empty Telegram allowlist (bot open to anyone).
# Without this, startup fails closed — see bootstrap.ensure_environment().
DEV_MODE = _flag("DEV_MODE")

# Ceiling on model requests per turn so a runaway tool loop cannot burn budget.
MAX_TURNS = int(_env("MAX_TURNS", "12"))

# Hard daily ceiling on estimated model spend (USD). 0 disables the guard.
DAILY_BUDGET_USD = float(_env("DAILY_BUDGET_USD", "5"))

# Max messages of session history fed back into a turn (0 = unlimited).
HISTORY_MAX_MESSAGES = int(_env("HISTORY_MAX_MESSAGES", "60"))

# Push to git remote after committing (best-effort; needs an 'origin' remote).
GIT_PUSH = _flag("GIT_PUSH", "false")

# Deployed mode only: where to clone the knowledge repo from on first boot,
# and an optional SSH deploy key (the key *contents*) for clone/push auth.
GIT_REMOTE_URL = _env("GIT_REMOTE_URL")
GIT_SSH_KEY = _env("GIT_SSH_KEY")

# --- PWA (Phase 10) -----------------------------------------------------------
# Public origin the app is served from; WebAuthn binds passkeys to this domain.
# Production: your Fly app URL (https://<app>.fly.dev). Local dev: localhost.
PWA_ORIGIN = (_env("PWA_ORIGIN", "http://localhost:8080") or "").rstrip("/")
PORT = int(_env("PORT", "8080"))

# --- Proactive scheduling (Phase 4) -----------------------------------------
# When enabled, the agent runs unattended jobs: a nightly wiki-synthesis pass and
# a morning briefing pushed to you on Telegram. Disabled if there's no chat to
# message. Times are local-hour ints; minutes are nudged off :00 to spread load.
PROACTIVE_ENABLED = _flag("PROACTIVE_ENABLED", "true")
SYNTHESIS_HOUR = int(_env("SYNTHESIS_HOUR", "3"))   # nightly inbox -> wiki
BRIEFING_HOUR = int(_env("BRIEFING_HOUR", "8"))     # morning briefing
REFLECT_HOUR = int(_env("REFLECT_HOUR", "4"))       # weekly (Sun) self-improvement
# Chat to push proactive messages to. Defaults to the (single) allowed user id —
# in a private chat the chat id equals the user id.
_chat = _env("TELEGRAM_CHAT_ID")
TELEGRAM_CHAT_ID = (
    int(_chat) if _chat
    else (sorted(TELEGRAM_ALLOWED_USER_IDS)[0] if TELEGRAM_ALLOWED_USER_IDS else None)
)
