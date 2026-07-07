"""PWA chat + approvals (slice P3). Turns are mocked — no model calls."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, UserPromptPart

from agent import loop as agent_loop
from agent import memory, spend
from api import auth
from api.server import PWA_SESSION, build_api


@pytest.fixture
def client(sandbox):
    auth.init_db()
    memory.init_db()
    spend.init_db()
    c = TestClient(build_api())
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session())
    return c


def _events(response_text: str) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in response_text.split("\n")
        if line.startswith("data: ")
    ]


def _messages():
    return [ModelRequest(parts=[UserPromptPart(content="hi")])]


def test_chat_requires_session(sandbox):
    auth.init_db()
    c = TestClient(build_api())
    assert c.post("/api/chat", json={"text": "hi"}).status_code == 401
    assert c.post("/api/approvals/x", json={"approve": True}).status_code == 401


def test_chat_rejects_empty(client):
    assert client.post("/api/chat", json={"text": "  "}).status_code == 400


def test_chat_streams_reply(client, monkeypatch):
    async def fake_run_turn(session_id, text, tier="default", directive=None):
        assert session_id == PWA_SESSION and text == "hello there"
        return agent_loop.TurnResult(text="captured it.")
    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    with client.stream("POST", "/api/chat", json={"text": "hello there"}) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        events = _events("".join(res.iter_text()))
    assert events[-1] == {"type": "reply", "text": "captured it."}


def test_chat_streams_budget_error(client, monkeypatch):
    async def broke(session_id, text, tier="default", directive=None):
        raise spend.BudgetExceeded("Daily budget reached.")
    monkeypatch.setattr(agent_loop, "run_turn", broke)
    with client.stream("POST", "/api/chat", json={"text": "hi"}) as res:
        events = _events("".join(res.iter_text()))
    assert events[-1]["type"] == "error"
    assert "budget" in events[-1]["text"].lower()


def test_chat_approval_then_decide(client, monkeypatch):
    async def pending_turn(session_id, text, tier="default", directive=None):
        return agent_loop.TurnResult(
            approvals=[agent_loop.ApprovalRequest("call_1", "vault_write", "write x.md")],
            resume_messages=_messages(),
        )
    monkeypatch.setattr(agent_loop, "run_turn", pending_turn)
    with client.stream("POST", "/api/chat", json={"text": "write it"}) as res:
        events = _events("".join(res.iter_text()))
    ev = events[-1]
    assert ev["type"] == "approval" and ev["items"] == ["write x.md"]

    seen = {}
    async def fake_resume(session_id, messages, decisions, tier="default"):
        seen.update(decisions)
        assert session_id == PWA_SESSION
        return agent_loop.TurnResult(text="written.")
    monkeypatch.setattr(agent_loop, "resume_turn", fake_resume)
    out = client.post(f"/api/approvals/{ev['token']}", json={"approve": True}).json()
    assert out == {"type": "reply", "text": "written."}
    assert seen == {"call_1": True}
    # The token is single-use.
    assert client.post(
        f"/api/approvals/{ev['token']}", json={"approve": True}
    ).status_code == 404


def test_approval_unknown_token_404(client):
    assert client.post("/api/approvals/nope", json={"approve": True}).status_code == 404


def test_telegram_pending_can_be_decided_in_pwa(client, monkeypatch):
    """The approval store is shared: a turn paused on Telegram can be approved here."""
    memory.save_pending("tgtok", "tg:42", "strong", ["c9"], _messages())
    captured = {}
    async def fake_resume(session_id, messages, decisions, tier="default"):
        captured["session"] = session_id
        captured["tier"] = tier
        return agent_loop.TurnResult(text="done on strong.")
    monkeypatch.setattr(agent_loop, "resume_turn", fake_resume)
    out = client.post("/api/approvals/tgtok", json={"approve": True}).json()
    assert out["type"] == "reply"
    assert captured == {"session": "tg:42", "tier": "strong"}
