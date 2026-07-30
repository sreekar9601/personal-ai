"""Activity feed (slice C2) — what the agent actually did, as a timeline.

The command-center home needs a visible trail: the point of an autonomous
agent is that things happened while you weren't looking. Two sources, merged:

  - `.data/audit.log`  — one JSONL line per side-effectful tool call (writes,
    moves, expenses, tasks, memory). Machine-written, complete, but noisy.
  - git log            — knowledge commits (turn / synthesis / briefing), the
    coarse-grained record that survives even if the local audit log is lost.

We classify each raw event into a small set of display kinds so the UI can
show an icon and a one-line summary without knowing about tool names.

Public surface:
    recent(limit=25) -> list[dict]   newest-first, typed timeline entries
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone

from . import config

# Tool name -> (kind, icon, verb). Kinds are UI categories, not tool names.
_TOOL_KINDS: dict[str, tuple[str, str, str]] = {
    "log_expense": ("expense", "💳", "Logged expense"),
    "add_task": ("task", "✅", "Added task"),
    "complete_task": ("task", "✅", "Completed task"),
    "remember": ("memory", "🧠", "Learned a fact"),
    "vault_write": ("note", "📝", "Wrote"),
    "vault_append": ("note", "📝", "Appended to"),
    "vault_move": ("archive", "📦", "Archived"),
    "finance_query": ("query", "🔍", "Queried finances"),
}

# Commit subject prefixes -> (kind, icon, label).
_COMMIT_KINDS: list[tuple[re.Pattern, tuple[str, str, str]]] = [
    (re.compile(r"^journal: .*briefing", re.I), ("briefing", "☀️", "Morning briefing")),
    (re.compile(r"^turn \(resumed", re.I), ("approval", "🔐", "Approved action ran")),
    (re.compile(r"^(wiki )?synth", re.I), ("synthesis", "🌀", "Synthesised the inbox")),
    (re.compile(r"^finance:", re.I), ("expense", "💳", "Finance update")),
    (re.compile(r"^tasks:", re.I), ("task", "✅", "Task list update")),
    (re.compile(r"^reflect", re.I), ("reflection", "🪞", "Reflection pass")),
    (re.compile(r"^turn:", re.I), ("turn", "💬", "Conversation")),
]


def _audit_events(limit: int) -> list[dict]:
    """Tail the audit log and classify the interesting lines."""
    path = config.DATA_DIR / "audit.log"
    if not path.is_file():
        return []
    try:
        # Personal scale: the log is small; read the tail cheaply.
        lines = path.read_text(errors="replace").splitlines()[-(limit * 6):]
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        tool = rec.get("tool", "")
        mapping = _TOOL_KINDS.get(tool)
        if not mapping:
            continue
        kind, icon, verb = mapping
        args = rec.get("args") or {}
        detail = ""
        if isinstance(args, dict):
            if tool == "log_expense":
                amount = args.get("amount")
                detail = f"{amount} · {args.get('description', '')}".strip(" ·")
            elif tool in ("add_task", "complete_task"):
                detail = str(args.get("text") or args.get("match") or "")
            elif tool == "remember":
                detail = str(args.get("fact") or "")
            else:
                detail = str(args.get("rel_path") or args.get("dst") or "")
        status = str(rec.get("status") or "")
        out.append({
            "ts": rec.get("ts") or "",
            "kind": kind,
            "icon": icon,
            "title": verb,
            "detail": detail[:120],
            "ok": not status.startswith("[refused") and not status.startswith("[blocked"),
            "source": "audit",
        })
        if len(out) >= limit:
            break
    return out


def _git_events(limit: int) -> list[dict]:
    """Recent knowledge commits, classified by subject."""
    if not (config.REPO_ROOT / ".git").is_dir():
        return []
    try:
        res = subprocess.run(
            ["git", "log", f"-{limit}", "--date=iso-strict", "--format=%cd%x1f%s"],
            cwd=config.REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    out: list[dict] = []
    for line in res.stdout.splitlines():
        date_str, _, subject = line.partition("\x1f")
        if not subject:
            continue
        kind = icon = label = None
        for pattern, (k, i, lbl) in _COMMIT_KINDS:
            if pattern.search(subject):
                kind, icon, label = k, i, lbl
                break
        if not kind:
            continue  # code commits etc. are not agent activity
        detail = subject.split(":", 1)[-1].strip() if ":" in subject else ""
        # Don't echo the label back as its own detail ("Morning briefing —
        # morning briefing"); the commit subject often restates it.
        if detail.lower() in label.lower() or label.lower() in detail.lower():
            detail = ""
        out.append({
            "ts": date_str.strip(),
            "kind": kind,
            "icon": icon,
            "title": label,
            "detail": detail[:120],
            "ok": True,
            "source": "git",
        })
    return out


def _sort_key(entry: dict) -> str:
    """ISO timestamps sort lexically once normalised to UTC-ish strings."""
    ts = entry.get("ts") or ""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ts


def recent(limit: int = 25) -> list[dict]:
    """Merged, newest-first activity timeline. Never raises."""
    limit = max(1, min(int(limit), 100))
    events = _audit_events(limit) + _git_events(limit)
    events.sort(key=_sort_key, reverse=True)
    # Collapse adjacent duplicates (a tool call and its commit describing the
    # same action) so the feed reads like a story, not a log.
    deduped: list[dict] = []
    for e in events:
        prev = deduped[-1] if deduped else None
        if prev and prev["kind"] == e["kind"] and prev["detail"] == e["detail"]:
            continue
        deduped.append(e)
    return deduped[:limit]
