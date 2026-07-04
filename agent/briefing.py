"""The morning briefing (Phase 4) — a deterministic daily status pull.

A briefing should never cost a model call or hallucinate a number, so this
gathers hard facts straight from the repo: how full the inbox is, which job
applications have a next action due, and the month's spend so far. The text is
assembled from those facts, written to the day's journal page, and (by the
scheduler) pushed to you on Telegram.

Public surface:
  build() -> str        the briefing text (also persisted to vault/journal/)
"""
from __future__ import annotations

from datetime import date

from . import config, finance

_TERMINAL_STATUSES = {"offer", "rejected", "withdrawn", "hired"}


def _inbox_count() -> int:
    inbox = config.VAULT_DIR / "00-inbox"
    return len(list(inbox.glob("*.md"))) if inbox.is_dir() else 0


def _job_next_actions() -> list[str]:
    """Active applications with their next action, parsed from the CRM tracker."""
    path = config.VAULT_DIR / "crm" / "applications.md"
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0].lower() in ("company", "") or set(cells[0]) <= {"-"}:
            continue  # header / separator
        company, _role, status, _applied, next_action = cells[0], cells[1], cells[2], cells[3], cells[4]
        if status.lower() in _TERMINAL_STATUSES:
            continue
        if next_action:
            out.append(f"{company} ({status}): {next_action}")
    return out


def _finance_line() -> str:
    month = date.today().strftime("%Y-%m")
    try:
        s = finance.summary(month)
    except Exception:
        return ""
    t = s["totals"]
    if not t or t.get("spent") is None:
        return ""
    uncat = sum(r["n"] for r in s["by_category"] if r["category"] == "uncategorized")
    spent = abs(t.get("spent") or 0)
    tail = f" · {uncat} uncategorised" if uncat else ""
    return f"Spent ${spent:.0f} this month{tail}."


def build() -> str:
    """Assemble today's briefing, persist it to the journal, and return the text."""
    today = date.today().isoformat()
    lines = [f"# Briefing — {today}", ""]

    inbox = _inbox_count()
    if inbox:
        lines.append(f"- 📥 {inbox} note(s) in the inbox awaiting synthesis (/synthesize).")

    actions = _job_next_actions()
    if actions:
        lines.append("- 💼 Job next actions:")
        lines.extend(f"    - {a}" for a in actions)

    fin = _finance_line()
    if fin:
        lines.append(f"- 💳 {fin}")

    if len(lines) == 2:  # only the header
        lines.append("- All clear. Nothing pending.")

    text = "\n".join(lines)

    # Persist to the day's journal page (best-effort; journal is auto-approved).
    if not config.KILL_SWITCH:
        page = config.VAULT_DIR / "journal" / f"{today}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        if not page.exists():
            page.write_text(text + "\n")
    return text
