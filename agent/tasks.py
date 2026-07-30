"""Tasks (slice C1) — a markdown checkbox store the agent and the app share.

`vault/tasks.md` is the single source of truth, in Obsidian-native syntax so
it stays hand-editable on the desktop:

    - [ ] renew passport 📅 2026-08-20 #errand
    - [x] email landlord ✅ 2026-07-02

Design, matching the finance ledger: **the model supplies fields, code does the
writing.** Parsing is tolerant (any `- [ ]`/`- [x]` line counts, metadata is
optional and order-insensitive); writing is deterministic and append-only for
new tasks, so a hand-edited file is never reformatted wholesale.

Public surface:
    list_tasks(include_done=False) -> list[Task]
    add_task(text, due=None, tag=None)        -> str
    complete_task(match)                      -> str
    reopen_task(match)                        -> str
    agenda()                                  -> dict   (overdue/today/soon/later)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import config

TASKS_REL = "vault/tasks.md"

_HEADER = "# Tasks\n\nOne task per line. `📅 YYYY-MM-DD` sets a due date;\n`#tag` groups.\n\n"

_LINE_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<body>.*)$")
_DUE_RE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
_DONE_RE = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})")
_TAG_RE = re.compile(r"#([\w/-]+)")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Task:
    text: str
    done: bool = False
    due: str | None = None
    done_on: str | None = None
    tags: list[str] = field(default_factory=list)
    line_no: int = -1  # 0-based index into the file's lines

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "done": self.done,
            "due": self.due,
            "done_on": self.done_on,
            "tags": self.tags,
            "id": self.line_no,
            "overdue": bool(
                not self.done and self.due and self.due < date.today().isoformat()
            ),
        }


def _path():
    return config.REPO_ROOT / TASKS_REL


def _read_lines() -> list[str]:
    path = _path()
    if not path.exists():
        return []
    return path.read_text().splitlines()


def _write_lines(lines: list[str]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n")


def _parse_line(raw: str, line_no: int) -> Task | None:
    m = _LINE_RE.match(raw)
    if not m:
        return None
    body = m.group("body")
    due = _DUE_RE.search(body)
    done_on = _DONE_RE.search(body)
    tags = _TAG_RE.findall(body)
    text = _DUE_RE.sub("", body)
    text = _DONE_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return Task(
        text=" ".join(text.split()),
        done=m.group("mark").lower() == "x",
        due=due.group(1) if due else None,
        done_on=done_on.group(1) if done_on else None,
        tags=tags,
        line_no=line_no,
    )


def list_tasks(include_done: bool = False) -> list[Task]:
    """All tasks in file order. Open tasks sort first by due date when listed."""
    out: list[Task] = []
    for i, raw in enumerate(_read_lines()):
        task = _parse_line(raw, i)
        if task and (include_done or not task.done):
            out.append(task)
    return out


def _render(task_text: str, due: str | None, tag: str | None) -> str:
    parts = [f"- [ ] {task_text}"]
    if due:
        parts.append(f"📅 {due}")
    if tag:
        parts.append(f"#{tag.lstrip('#')}")
    return " ".join(parts)


def add_task(text: str, due: str | None = None, tag: str | None = None) -> str:
    """Append one open task. Returns a one-line confirmation."""
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; task writes are disabled."
    text = " ".join(str(text or "").split())[:200]
    if not text:
        return "[refused] task text is required."
    if due and not _ISO_RE.match(due):
        return "[refused] due must be YYYY-MM-DD."
    lines = _read_lines()
    if not lines:
        lines = _HEADER.rstrip("\n").splitlines()
    # Duplicate open task? Don't pile up.
    for task in list_tasks():
        if task.text.lower() == text.lower():
            return f"[known] already on the list: {text}"
    lines.append(_render(text, due, tag))
    _write_lines(lines)
    suffix = f" (due {due})" if due else ""
    return f"[added] {text}{suffix}"


def _find(match: str, done: bool) -> Task | None:
    """First task whose text contains `match` (case-insensitive) in the given state."""
    needle = " ".join(str(match or "").split()).lower()
    if not needle:
        return None
    for task in list_tasks(include_done=True):
        if task.done == done and needle in task.text.lower():
            return task
    return None


def complete_task(match: str) -> str:
    """Tick the first open task matching `match`."""
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; task writes are disabled."
    task = _find(match, done=False)
    if not task:
        return f"[not found] no open task matching {match!r}."
    lines = _read_lines()
    raw = lines[task.line_no]
    updated = re.sub(r"\[\s\]", "[x]", raw, count=1).rstrip()
    if not _DONE_RE.search(updated):
        updated += f" ✅ {date.today().isoformat()}"
    lines[task.line_no] = updated
    _write_lines(lines)
    return f"[done] {task.text}"


def reopen_task(match: str) -> str:
    """Un-tick the first completed task matching `match`."""
    if config.KILL_SWITCH:
        return "[blocked] KILL_SWITCH is on; task writes are disabled."
    task = _find(match, done=True)
    if not task:
        return f"[not found] no completed task matching {match!r}."
    lines = _read_lines()
    raw = lines[task.line_no]
    updated = re.sub(r"\[[xX]\]", "[ ]", raw, count=1)
    updated = _DONE_RE.sub("", updated)
    lines[task.line_no] = " ".join(updated.split())
    _write_lines(lines)
    return f"[reopened] {task.text}"


def agenda() -> dict:
    """Open tasks bucketed for a daily view."""
    today = date.today().isoformat()
    buckets: dict[str, list[dict]] = {
        "overdue": [], "today": [], "soon": [], "later": [], "undated": []
    }
    for task in list_tasks():
        d = task.to_dict()
        if not task.due:
            buckets["undated"].append(d)
        elif task.due < today:
            buckets["overdue"].append(d)
        elif task.due == today:
            buckets["today"].append(d)
        else:
            buckets["soon" if task.due <= _plus_days(7) else "later"].append(d)
    for key in ("overdue", "today", "soon", "later"):
        buckets[key].sort(key=lambda t: t["due"] or "")
    return buckets


def _plus_days(n: int) -> str:
    from datetime import timedelta

    return (date.today() + timedelta(days=n)).isoformat()


def summary_line() -> str:
    """One-line status for briefings/overview: '3 open · 1 overdue · 1 due today'."""
    tasks = list_tasks()
    today = date.today().isoformat()
    overdue = sum(1 for t in tasks if t.due and t.due < today)
    due_today = sum(1 for t in tasks if t.due == today)
    bits = [f"{len(tasks)} open"]
    if overdue:
        bits.append(f"{overdue} overdue")
    if due_today:
        bits.append(f"{due_today} due today")
    return " · ".join(bits)
