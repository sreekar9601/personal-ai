"""Tasks store + API (slice C1)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from agent import config, tasks
from api import auth
from api.server import build_api


def _iso(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# --- Store ---------------------------------------------------------------------
def test_add_and_list(sandbox):
    assert tasks.add_task("renew passport", due="2026-08-20", tag="errand").startswith(
        "[added]"
    )
    items = tasks.list_tasks()
    assert len(items) == 1
    t = items[0]
    assert t.text == "renew passport"
    assert t.due == "2026-08-20"
    assert t.tags == ["errand"]
    assert t.done is False


def test_parses_hand_written_file(sandbox):
    (sandbox / "vault" / "tasks.md").write_text(
        "# Tasks\n\n"
        "- [ ] call dentist 📅 2026-08-01 #health\n"
        "* [x] email landlord ✅ 2026-07-02\n"
        "- [ ] plain task\n"
        "not a task line\n"
    )
    open_tasks = tasks.list_tasks()
    assert [t.text for t in open_tasks] == ["call dentist", "plain task"]
    all_tasks = tasks.list_tasks(include_done=True)
    assert len(all_tasks) == 3
    done = [t for t in all_tasks if t.done][0]
    assert done.text == "email landlord" and done.done_on == "2026-07-02"


def test_complete_and_reopen(sandbox):
    tasks.add_task("call dentist")
    assert tasks.complete_task("dentist").startswith("[done]")
    assert tasks.list_tasks() == []
    body = (sandbox / "vault" / "tasks.md").read_text()
    assert "- [x] call dentist" in body and "✅" in body
    assert tasks.reopen_task("dentist").startswith("[reopened]")
    assert len(tasks.list_tasks()) == 1


def test_complete_no_match(sandbox):
    tasks.add_task("a task")
    assert tasks.complete_task("nonexistent").startswith("[not found]")


def test_dedupes_open_tasks(sandbox):
    tasks.add_task("renew passport")
    assert tasks.add_task("Renew Passport").startswith("[known]")
    assert len(tasks.list_tasks()) == 1


def test_validation_and_kill_switch(sandbox, monkeypatch):
    assert tasks.add_task("  ").startswith("[refused]")
    assert tasks.add_task("x", due="next tuesday").startswith("[refused]")
    monkeypatch.setattr(config, "KILL_SWITCH", True)
    assert tasks.add_task("x").startswith("[blocked]")
    assert tasks.complete_task("x").startswith("[blocked]")


def test_agenda_buckets(sandbox):
    tasks.add_task("late thing", due=_iso(-3))
    tasks.add_task("today thing", due=_iso(0))
    tasks.add_task("soon thing", due=_iso(3))
    tasks.add_task("far thing", due=_iso(30))
    tasks.add_task("someday thing")
    a = tasks.agenda()
    assert [t["text"] for t in a["overdue"]] == ["late thing"]
    assert [t["text"] for t in a["today"]] == ["today thing"]
    assert [t["text"] for t in a["soon"]] == ["soon thing"]
    assert [t["text"] for t in a["later"]] == ["far thing"]
    assert [t["text"] for t in a["undated"]] == ["someday thing"]
    assert a["overdue"][0]["overdue"] is True


def test_summary_line(sandbox):
    tasks.add_task("late", due=_iso(-1))
    tasks.add_task("now", due=_iso(0))
    tasks.add_task("plain")
    s = tasks.summary_line()
    assert "3 open" in s and "1 overdue" in s and "1 due today" in s


# --- API -------------------------------------------------------------------------
@pytest.fixture
def client(sandbox):
    auth.init_db()
    c = TestClient(build_api())
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session())
    return c


def test_tasks_api_requires_session(sandbox):
    auth.init_db()
    assert TestClient(build_api()).get("/api/tasks").status_code == 401


def test_tasks_api_crud(client):
    assert client.get("/api/tasks").json()["tasks"] == []
    out = client.post("/api/tasks", json={"text": "renew passport", "due": "2026-08-20"})
    assert out.status_code == 200 and out.json()["result"].startswith("[added]")
    body = client.get("/api/tasks").json()
    assert body["tasks"][0]["text"] == "renew passport"
    assert "1 open" in body["summary"]
    done = client.patch("/api/tasks", json={"match": "passport", "done": True})
    assert done.json()["result"].startswith("[done]")
    assert client.get("/api/tasks").json()["tasks"] == []


def test_tasks_api_errors(client):
    assert client.post("/api/tasks", json={"text": ""}).status_code == 400
    assert client.patch("/api/tasks", json={"match": "ghost"}).status_code == 404


# --- Briefing integration ----------------------------------------------------------
def test_briefing_includes_due_tasks(sandbox):
    from agent import briefing

    tasks.add_task("overdue thing", due=_iso(-2))
    tasks.add_task("today thing", due=_iso(0))
    text = briefing.build()
    assert "Overdue" in text and "overdue thing" in text
    assert "Due today" in text and "today thing" in text
