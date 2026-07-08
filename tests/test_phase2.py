"""Phase 2 critical fixes: fail-closed startup, persistent approvals,
history bounding, and the daily spend guard."""
from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RunUsage

from agent import bootstrap, config, memory, spend


# --- Fail-closed access control ------------------------------------------------
def test_empty_allowlist_aborts_startup(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", set())
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEPLOYED", False)
    with pytest.raises(SystemExit):
        bootstrap.ensure_environment()


def test_dev_mode_allows_empty_allowlist(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", set())
    monkeypatch.setattr(config, "DEV_MODE", True)
    monkeypatch.setattr(config, "DEPLOYED", False)
    bootstrap.ensure_environment()  # must not raise


def test_allowlist_set_passes(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", {123})
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEPLOYED", False)
    bootstrap.ensure_environment()  # must not raise


def test_app_only_mode_needs_no_allowlist(monkeypatch):
    """No bot token -> no Telegram surface -> the passkey is the access control."""
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", set())
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEPLOYED", False)
    bootstrap.ensure_environment()  # must not raise


def test_deployed_without_volume_aborts(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", {123})
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEPLOYED", True)
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "missing-volume")
    with pytest.raises(SystemExit):
        bootstrap.ensure_environment()


# --- History bounding ------------------------------------------------------------
def _turn(i: int) -> list:
    return [
        ModelRequest(parts=[UserPromptPart(content=f"message {i}")]),
        ModelResponse(parts=[TextPart(content=f"reply {i}")]),
    ]


def test_history_is_bounded(sandbox, monkeypatch):
    monkeypatch.setattr(config, "HISTORY_MAX_MESSAGES", 6)
    memory.init_db()
    msgs = [m for i in range(20) for m in _turn(i)]
    memory.save_history("s1", msgs)
    loaded = memory.load_history("s1")
    assert len(loaded) <= 6
    # The window must start on a user-prompt request, not an orphaned tool cycle.
    first = loaded[0]
    assert isinstance(first, ModelRequest)
    assert any(isinstance(p, UserPromptPart) for p in first.parts)
    # The most recent exchange is retained.
    assert any(
        isinstance(p, TextPart) and p.content == "reply 19"
        for m in loaded if isinstance(m, ModelResponse) for p in m.parts
    )


def test_history_unbounded_when_disabled(sandbox, monkeypatch):
    monkeypatch.setattr(config, "HISTORY_MAX_MESSAGES", 0)
    memory.init_db()
    msgs = [m for i in range(10) for m in _turn(i)]
    memory.save_history("s1", msgs)
    assert len(memory.load_history("s1")) == 20


# --- Persistent pending approvals -------------------------------------------------
def test_pending_approval_round_trip(sandbox):
    memory.init_db()
    msgs = _turn(1)
    memory.save_pending("tok1", "tg:42", "strong", ["call_a", "call_b"], msgs)
    popped = memory.pop_pending("tok1")
    assert popped is not None
    session_id, messages, tier, call_ids = popped
    assert session_id == "tg:42"
    assert tier == "strong"
    assert call_ids == ["call_a", "call_b"]
    assert len(messages) == len(msgs)
    # pop is destructive: a second tap of the button finds nothing.
    assert memory.pop_pending("tok1") is None


def test_pending_approval_unknown_token(sandbox):
    memory.init_db()
    assert memory.pop_pending("nope") is None


# --- Daily spend guard -------------------------------------------------------------
def test_spend_records_and_accumulates(sandbox):
    spend.init_db()
    usage = RunUsage(input_tokens=1_000_000, output_tokens=100_000)
    spend.record("anthropic:claude-sonnet-4-6", usage)
    spend.record("anthropic:claude-sonnet-4-6", usage)
    day = spend.today()
    assert day["input_tokens"] == 2_000_000
    assert day["output_tokens"] == 200_000
    assert day["cost_usd"] == pytest.approx(2 * (3.0 + 0.1 * 15.0), rel=1e-6)


def test_budget_guard_trips(sandbox, monkeypatch):
    spend.init_db()
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.5)
    spend.check_budget()  # nothing spent yet
    spend.record(
        "anthropic:claude-sonnet-4-6", RunUsage(input_tokens=1_000_000, output_tokens=0)
    )  # ~$3 estimated
    with pytest.raises(spend.BudgetExceeded):
        spend.check_budget()


def test_budget_guard_disabled_at_zero(sandbox, monkeypatch):
    spend.init_db()
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.0)
    spend.record(
        "anthropic:claude-opus-4-8", RunUsage(input_tokens=10_000_000, output_tokens=0)
    )
    spend.check_budget()  # must not raise
