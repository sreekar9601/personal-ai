"""Activity feed (slice C2) + the Overview bootstrap payload (slice C3)."""
from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from agent import activity, audit, spend, tasks
from api import auth
from api.server import build_api


def _audit_line(sandbox, tool, args, status="[ok]", ts="2026-07-30T10:00:00+00:00"):
    path = sandbox / ".data" / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": ts, "tool": tool, "args": args, "status": status}) + "\n")


def test_classifies_audit_events(sandbox):
    _audit_line(sandbox, "log_expense", {"amount": 450, "description": "BigBasket"})
    _audit_line(sandbox, "add_task", {"text": "renew passport"})
    _audit_line(sandbox, "remember", {"fact": "prefers brief replies"})
    events = activity.recent()
    kinds = {e["kind"] for e in events}
    assert {"expense", "task", "memory"} <= kinds
    expense = [e for e in events if e["kind"] == "expense"][0]
    assert expense["title"] == "Logged expense"
    assert "BigBasket" in expense["detail"]
    assert expense["ok"] is True


def test_refused_events_marked_not_ok(sandbox):
    _audit_line(sandbox, "vault_write", {"rel_path": "x.md"}, status="[refused] nope")
    events = activity.recent()
    assert events and events[0]["ok"] is False


def test_unknown_tools_are_filtered_out(sandbox):
    _audit_line(sandbox, "some_internal_thing", {"x": 1})
    assert activity.recent() == []


def test_ignores_malformed_lines(sandbox):
    path = sandbox / ".data" / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json\n")
    _audit_line(sandbox, "add_task", {"text": "ok task"})
    events = activity.recent()
    assert len(events) == 1 and events[0]["kind"] == "task"


def test_newest_first_ordering(sandbox):
    _audit_line(sandbox, "add_task", {"text": "older"}, ts="2026-07-29T08:00:00+00:00")
    _audit_line(sandbox, "log_expense", {"amount": 1, "description": "newer"},
                ts="2026-07-30T09:00:00+00:00")
    events = activity.recent()
    assert events[0]["detail"].endswith("newer")


def test_includes_classified_git_commits(sandbox):
    subprocess.run(["git", "init", "-q"], cwd=sandbox, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=sandbox, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=sandbox, check=True)
    (sandbox / "vault" / "note.md").write_text("hi")
    subprocess.run(["git", "add", "-A"], cwd=sandbox, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "journal: morning briefing"], cwd=sandbox, check=True
    )
    events = activity.recent()
    assert any(e["kind"] == "briefing" and e["source"] == "git" for e in events)


def test_no_sources_is_empty_not_error(sandbox):
    assert activity.recent() == []


def test_limit_is_clamped(sandbox):
    for i in range(30):
        _audit_line(sandbox, "add_task", {"text": f"task {i}"})
    assert len(activity.recent(limit=5)) == 5
    assert len(activity.recent(limit=99999)) <= 100


# --- API / Overview ------------------------------------------------------------------
@pytest.fixture
def client(sandbox):
    auth.init_db()
    spend.init_db()
    c = TestClient(build_api())
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session())
    return c


def test_activity_endpoint_requires_session(sandbox):
    auth.init_db()
    assert TestClient(build_api()).get("/api/activity").status_code == 401


def test_activity_endpoint(client, sandbox):
    _audit_line(sandbox, "log_expense", {"amount": 12, "description": "coffee"})
    events = client.get("/api/activity?limit=5").json()["events"]
    assert events[0]["kind"] == "expense"


def test_bootstrap_has_overview_payload(client, sandbox):
    tasks.add_task("renew passport", due="2026-08-20")
    _audit_line(sandbox, "add_task", {"text": "renew passport"})
    body = client.get("/api/bootstrap").json()
    assert {"status", "finance", "month", "spent_today", "tasks", "activity"} <= body.keys()
    assert "1 open" in body["tasks"]["summary"]
    assert body["tasks"]["agenda"]["later"][0]["text"] == "renew passport"
    assert body["activity"][0]["kind"] == "task"
    assert isinstance(body["spent_today"], (int, float))


def test_audit_record_feeds_activity(sandbox):
    """End-to-end: the real audit writer produces feed-able events."""
    audit.record("log_expense", {"amount": 99, "description": "test buy"}, "[logged]")
    events = activity.recent()
    assert events and events[0]["kind"] == "expense" and "test buy" in events[0]["detail"]
