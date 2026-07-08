"""Regression: a full run_turn() must record spend from the real result shape.

pydantic-ai v2 made AgentRunResult.usage a *property*; calling it as a method
crashed every live turn ('RunUsage' object is not callable) while all other
tests passed, because they mocked run_turn itself. This test stubs one level
lower — agent.run — so the accounting path runs against the property shape.
"""
from __future__ import annotations

import asyncio

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RunUsage

from agent import loop as agent_loop
from agent import memory, spend


class FakeRunResult:
    output = "captured."
    usage = RunUsage(input_tokens=1000, output_tokens=200)  # property-like attribute

    def all_messages(self):
        return [
            ModelRequest(parts=[UserPromptPart(content="hi")]),
            ModelResponse(parts=[TextPart(content="captured.")]),
        ]


def test_run_turn_records_spend(sandbox, monkeypatch):
    memory.init_db()
    spend.init_db()

    async def fake_agent_run(*args, **kwargs):
        return FakeRunResult()

    monkeypatch.setattr(agent_loop.agent, "run", fake_agent_run)
    result = asyncio.run(agent_loop.run_turn("test:sess", "hello"))
    assert result.text == "captured."
    day = spend.today()
    assert day["input_tokens"] == 1000
    assert day["output_tokens"] == 200
    assert day["cost_usd"] > 0


def test_resume_turn_records_spend(sandbox, monkeypatch):
    memory.init_db()
    spend.init_db()

    async def fake_agent_run(*args, **kwargs):
        return FakeRunResult()

    monkeypatch.setattr(agent_loop.agent, "run", fake_agent_run)
    result = asyncio.run(
        agent_loop.resume_turn("test:sess", FakeRunResult().all_messages(), {"c1": True})
    )
    assert result.text == "captured."
    assert spend.today()["input_tokens"] == 1000
