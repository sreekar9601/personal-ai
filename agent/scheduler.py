"""Proactive jobs (Phase 4) — registered on the APScheduler that main.py starts.

Phase 0 wired an idle scheduler; this fills it with two unattended jobs:

  - nightly synthesis: run the wiki-synthesis loop over the inbox while you sleep,
    so the wiki is current by morning. Runs quietly (it commits to git itself).
  - morning briefing: assemble the day's briefing and push it to you on Telegram.

Both are no-ops unless PROACTIVE_ENABLED and a chat target exist, and both honour
the kill switch (synthesis/briefing writes are gated downstream).
"""
from __future__ import annotations

import logging

from apscheduler.triggers.cron import CronTrigger

from . import briefing, config, gitsync, reflect, synthesis

log = logging.getLogger("personal-ai.scheduler")

_SYNTH_SESSION = "cron:synthesis"
_REFLECT_SESSION = "cron:reflect"


async def _push(title: str, body: str, tag: str) -> None:
    """Mirror a proactive message to the PWA's lock screen. Best-effort; the
    import is lazy so the scheduler never depends on the API package at load."""
    try:
        import asyncio

        from api import push as api_push

        await asyncio.to_thread(api_push.send_to_all, title, body, tag)
    except Exception:  # push must never break a job
        log.exception("web push failed")


async def _nightly_synthesis() -> None:
    if config.KILL_SWITCH:
        return
    try:
        result = await synthesis.synthesize(_SYNTH_SESSION)
        log.info("nightly synthesis: %s", (result.text or "")[:120])
    except Exception:  # never let a job crash the scheduler
        log.exception("nightly synthesis failed")


def _make_reflect_job(bot, chat_id: int):
    async def _weekly_reflection() -> None:
        if config.KILL_SWITCH:
            return
        try:
            result = await reflect.reflect(_REFLECT_SESSION)
            if result.text:
                await bot.send_message(chat_id, f"🧠 Weekly reflection:\n{result.text}")
                await _push("Weekly reflection", result.text, "reflection")
            log.info("weekly reflection done")
        except Exception:
            log.exception("weekly reflection failed")

    return _weekly_reflection


def _make_briefing_job(bot, chat_id: int):
    async def _morning_briefing() -> None:
        try:
            text = briefing.build()
            gitsync.commit_knowledge("journal: morning briefing")
            await bot.send_message(chat_id, text)
            await _push("Morning briefing", text, "briefing")
            log.info("briefing sent to %s", chat_id)
        except Exception:
            log.exception("morning briefing failed")

    return _morning_briefing


def register(scheduler, bot) -> bool:
    """Add the proactive jobs to a running scheduler. Returns True if armed."""
    if not config.PROACTIVE_ENABLED:
        log.info("proactive jobs disabled (PROACTIVE_ENABLED=false).")
        return False
    if config.TELEGRAM_CHAT_ID is None:
        log.warning("proactive jobs skipped: no TELEGRAM_CHAT_ID / allowed user.")
        return False

    scheduler.add_job(
        _nightly_synthesis,
        CronTrigger(hour=config.SYNTHESIS_HOUR, minute=7),
        id="nightly_synthesis",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_briefing_job(bot, config.TELEGRAM_CHAT_ID),
        CronTrigger(hour=config.BRIEFING_HOUR, minute=2),
        id="morning_briefing",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_reflect_job(bot, config.TELEGRAM_CHAT_ID),
        CronTrigger(day_of_week="sun", hour=config.REFLECT_HOUR, minute=13),
        id="weekly_reflection",
        replace_existing=True,
    )
    log.info(
        "proactive jobs armed: synthesis @%02d:07, briefing @%02d:02, "
        "reflection Sun @%02d:13 -> chat %s",
        config.SYNTHESIS_HOUR, config.BRIEFING_HOUR, config.REFLECT_HOUR,
        config.TELEGRAM_CHAT_ID,
    )
    return True
