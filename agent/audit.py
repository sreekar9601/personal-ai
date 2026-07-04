"""Audit trail (Phase 6) — an append-only local record of side-effectful actions.

Git commits and vault/log.md capture *knowledge* changes, but they are curated by
the agent. The audit log is the opposite: a raw, machine-written JSONL line for
every side-effectful or sensitive tool call (writes, moves, memory updates,
finance queries), regardless of whether it succeeded. It lives in .data/ (local,
gitignored) so it can't be quietly rewritten through the normal vault tools.

Best-effort by design: auditing must never break a turn.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config

AUDIT_LOG = config.DATA_DIR / "audit.log"


def record(tool: str, args: dict | str, status: str, session_id: str | None = None) -> None:
    """Append one audit line. Never raises."""
    try:
        if isinstance(args, dict):
            safe_args = {k: (v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v)
                         for k, v in args.items()}
        else:
            safe_args = str(args)[:240]
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": session_id,
            "tool": tool,
            "status": status,
            "args": safe_args,
        }, default=str)
        config.DATA_DIR.mkdir(exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:  # pragma: no cover - auditing is best-effort
        pass
