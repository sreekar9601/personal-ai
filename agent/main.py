"""Entrypoint: Telegram bot (+ scheduler placeholder) forwarding to the agent.

Surface:
  - any text message  -> default-tier turn (capture / chat, with vault retrieval)
  - /spec <idea>      -> strong-tier turn that writes a spec to vault/01-projects/
  - /synthesize       -> strong-tier wiki synthesis pass over the inbox (Phase 1)
  - inline buttons    -> approve/deny writes outside the auto-approve allowlist

Access is restricted to TELEGRAM_ALLOWED_USER_IDS. The scheduler runs the Phase 4
proactive jobs: a nightly synthesis pass and a morning briefing (see
agent/scheduler.py), both gated by PROACTIVE_ENABLED.
"""
from __future__ import annotations

import logging
import time
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import (
    bootstrap,
    briefing,
    config,
    finance,
    gitsync,
    jobs,
    loop,
    memory,
    providers,
    reflect,
    retrieval,
    scheduler as scheduler_jobs,
    spend,
    synthesis,
)
from .loop import TurnResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("personal-ai")

_STARTED = time.monotonic()  # for /status uptime

SPEC_DIRECTIVE = (
    "The user wants a detailed spec. Follow the spec-writing playbook"
    " (playbooks/spec-writing.md — read it). Produce a thorough spec and save it"
    " with vault_write to 'vault/01-projects/<kebab-title>.md'. Then reply with a"
    " short summary and the file path."
)


def _authorized(update: Update) -> bool:
    user = update.effective_user
    if not config.TELEGRAM_ALLOWED_USER_IDS:
        return True  # no allowlist configured -> open (dev only)
    return bool(user and user.id in config.TELEGRAM_ALLOWED_USER_IDS)


def _session_id(update: Update) -> str:
    return f"tg:{update.effective_chat.id}"


async def _deliver(update: Update, result: TurnResult, tier: str = "default") -> None:
    """Send a TurnResult to the user, rendering an approval prompt if needed.

    `tier` is the tier the turn ran on, so an approved resume continues on the
    same model. Pending approvals are persisted (they survive restarts)."""
    if result.needs_approval:
        token = uuid.uuid4().hex[:12]
        call_ids = [r.tool_call_id for r in result.approvals]
        memory.save_pending(
            token, _session_id(update), tier, call_ids, result.resume_messages
        )
        lines = ["🔐 *Approval needed* for write(s) outside the auto-approve zone:\n"]
        for r in result.approvals:
            lines.append(f"• `{r.summary}`\n")
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Approve", callback_data=f"ok:{token}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"no:{token}"),
            ]]
        )
        await update.effective_message.reply_text(
            "".join(lines), reply_markup=keyboard, parse_mode="Markdown"
        )
    else:
        await update.effective_message.reply_text(result.text or "(no output)")


async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_text(
        "Personal AI online. Send an idea to capture it, /spec <idea> for a full"
        " spec, or /synthesize to fold the inbox into the wiki."
    )


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    text = update.effective_message.text or ""
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        result = await loop.run_turn(_session_id(update), text, tier="default")
    except spend.BudgetExceeded as e:
        await update.effective_message.reply_text(f"💸 {e}")
        return
    except Exception as e:  # surface failures rather than going silent
        log.exception("turn failed")
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    await _deliver(update, result)


async def on_spec(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    idea = " ".join(ctx.args) if ctx.args else ""
    if not idea:
        await update.effective_message.reply_text("Usage: /spec <your idea>")
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        result = await loop.run_turn(
            _session_id(update), idea, tier="strong", directive=SPEC_DIRECTIVE
        )
    except Exception as e:
        log.exception("spec failed")
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    await _deliver(update, result, tier="strong")


async def on_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.effective_message.reply_text(
            "Usage: /job <posting, status update, or question>\n"
            "e.g. /job applied to Acme as Staff Eng — link …"
        )
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        result = await jobs.track(_session_id(update), text)
    except Exception as e:
        log.exception("job failed")
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    await _deliver(update, result, tier="strong")


async def on_import(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    res = finance.import_new()
    if res.get("blocked"):
        await update.effective_message.reply_text("KILL_SWITCH is on; import disabled.")
        return
    from . import gitsync

    gitsync.commit_knowledge("finance: import transactions")
    await update.effective_message.reply_text(
        f"Imported {res['files']} file(s): {res['added']} new transaction(s), "
        f"{res['skipped']} duplicate(s) skipped."
    )


async def on_finance(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    month = ctx.args[0] if ctx.args else None  # 'YYYY-MM' or omitted = all-time
    try:
        s = finance.summary(month)
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    t = s["totals"]
    lines = [f"*Finance — {s['period']}*"]
    if t.get("spent") is None and not s["by_category"]:
        lines.append("\nLedger is empty. Drop a CSV in `finance/imports/` and /import.")
    else:
        lines.append(f"Spent: {t.get('spent') or 0} · Income: {t.get('income') or 0}\n")
        for r in s["by_category"]:
            lines.append(f"• {r['category']}: {r['net']} ({r['n']})")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def on_briefing(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    try:
        text = briefing.build()
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    from . import gitsync

    gitsync.commit_knowledge("journal: briefing (on demand)")
    await update.effective_message.reply_text(text)


async def on_synthesize(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        result = await synthesis.synthesize(_session_id(update))
    except Exception as e:
        log.exception("synthesis failed")
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    await _deliver(update, result, tier="strong")


async def on_reflect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        result = await reflect.reflect(_session_id(update))
    except Exception as e:
        log.exception("reflect failed")
        await update.effective_message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    await _deliver(update, result, tier="strong")


async def on_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """One-glance health check (PLAN.md §9.2): uptime, spend, sync, inbox."""
    if not _authorized(update):
        return
    up = int(time.monotonic() - _STARTED)
    hours, minutes = divmod(up // 60, 60)
    usage = spend.today()
    budget = config.DAILY_BUDGET_USD
    budget_line = (
        f"${usage['cost_usd']:.2f} of ${budget:.2f} est." if budget > 0
        else f"${usage['cost_usd']:.2f} est. (no ceiling)"
    )
    inbox = config.VAULT_DIR / "00-inbox"
    inbox_n = len(list(inbox.glob("*.md"))) if inbox.is_dir() else 0
    last = gitsync.last_commit() or "none yet"
    lines = [
        f"⏱ Uptime: {hours}h{minutes:02d}m"
        + (" · deployed" if config.DEPLOYED else " · local"),
        f"🧠 Models ({providers.provider_name()}): "
        + ", ".join(
            f"{t}={providers.model_for(t).split(':', 1)[-1]}"
            for t in ("cheap", "default", "strong")
        ),
        f"💰 Today: {budget_line} "
        f"({usage['input_tokens']:,} in / {usage['output_tokens']:,} out tokens)",
        f"📥 Inbox: {inbox_n} capture(s) waiting",
        f"🔄 Last knowledge commit: {last}",
        f"🛑 Kill switch: {'ON' if config.KILL_SWITCH else 'off'}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    query = update.callback_query
    await query.answer()
    action, _, token = query.data.partition(":")
    pending = memory.pop_pending(token)
    if not pending:
        await query.edit_message_text("This approval has expired.")
        return
    session_id, messages, tier, call_ids = pending
    approve = action == "ok"
    # Approve/deny every pending write in the batch.
    decisions = {cid: approve for cid in call_ids}
    await query.edit_message_text("✅ Approved — running." if approve else "❌ Denied.")
    try:
        result = await loop.resume_turn(session_id, messages, decisions, tier=tier)
    except Exception as e:
        log.exception("resume failed")
        await query.message.reply_text(f"⚠️ {type(e).__name__}: {e}")
        return
    await _deliver(update, result, tier=tier)


def build_app() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env.")
    _provider_keys = {
        "anthropic": config.ANTHROPIC_API_KEY,
        "openai": config.OPENAI_API_KEY,
        "gemini": config.GEMINI_API_KEY,
    }
    if not _provider_keys.get(providers.provider_name()):
        raise SystemExit(
            f"No API key for provider '{providers.provider_name()}'. "
            "Set it in .env (see .env.example)."
        )
    # Fails closed on an empty allowlist; prepares the volume layout when deployed.
    bootstrap.ensure_environment()
    memory.init_db()
    spend.init_db()
    retrieval.init_db()
    n = retrieval.reindex_vault()  # build the keyword index from the vault on disk
    log.info("Vault keyword index ready (%d files).", n)
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("spec", on_spec))
    app.add_handler(CommandHandler("synthesize", on_synthesize))
    app.add_handler(CommandHandler("job", on_job))
    app.add_handler(CommandHandler("import", on_import))
    app.add_handler(CommandHandler("finance", on_finance))
    app.add_handler(CommandHandler("briefing", on_briefing))
    app.add_handler(CommandHandler("reflect", on_reflect))
    app.add_handler(CommandHandler("status", on_status))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Scheduler runs the Phase 4 proactive jobs (nightly synthesis + briefing).
    scheduler = AsyncIOScheduler()
    scheduler.start()
    scheduler_jobs.register(scheduler, app.bot)
    app.bot_data["scheduler"] = scheduler
    return app


async def _amain() -> None:
    """Run the Telegram bot and the PWA's HTTP server in one asyncio loop.

    One process keeps sqlite access simple and lets both transports share the
    same brain (docs/PWA-DESIGN.md §2). uvicorn owns signal handling: when it
    exits (SIGTERM/SIGINT), the bot is stopped cleanly behind it.
    """
    import uvicorn

    from api import auth as api_auth
    from api import push as api_push
    from api.server import build_api

    app = build_app()
    api_auth.init_db()
    api_auth.ensure_enroll_token()
    api_push.init_db()
    api_push.ensure_vapid_keys()
    server = uvicorn.Server(
        uvicorn.Config(
            build_api(), host="0.0.0.0", port=config.PORT, log_config=None
        )
    )
    async with app:
        await app.updater.start_polling()
        await app.start()
        log.info("PWA listening on :%d (origin %s)", config.PORT, config.PWA_ORIGIN)
        try:
            await server.serve()
        finally:
            await app.updater.stop()
            await app.stop()


def main() -> None:
    import asyncio

    log.info("Personal AI starting (kill_switch=%s)", config.KILL_SWITCH)
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
