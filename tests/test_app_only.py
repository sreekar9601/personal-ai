"""App-only mode: the whole system runs with no Telegram configured."""
from __future__ import annotations

from agent import config, scheduler


class _FakeScheduler:
    def __init__(self):
        self.jobs = {}

    def add_job(self, fn, trigger, id, replace_existing=False):
        self.jobs[id] = fn


def test_scheduler_arms_without_bot(monkeypatch):
    monkeypatch.setattr(config, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", None)
    fake = _FakeScheduler()
    assert scheduler.register(fake, None) is True
    assert set(fake.jobs) == {
        "nightly_synthesis", "morning_briefing", "weekly_reflection"
    }


def test_scheduler_respects_proactive_flag(monkeypatch):
    monkeypatch.setattr(config, "PROACTIVE_ENABLED", False)
    fake = _FakeScheduler()
    assert scheduler.register(fake, None) is False
    assert fake.jobs == {}


async def _run(coro):
    return await coro


def test_briefing_job_pushes_without_bot(sandbox, monkeypatch):
    """With bot=None the briefing still builds, commits, and web-pushes."""
    import asyncio

    from agent import briefing as briefing_mod

    monkeypatch.setattr(briefing_mod, "build", lambda: "Good morning — 2 tasks.")
    pushed = {}

    async def fake_push(title, body, tag):
        pushed.update(title=title, tag=tag)

    monkeypatch.setattr(scheduler, "_push", fake_push)
    job = scheduler._make_briefing_job(None, None)
    asyncio.run(job())
    assert pushed == {"title": "Morning briefing", "tag": "briefing"}
