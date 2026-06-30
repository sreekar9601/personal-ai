"""Entrypoint: Telegram bot (+ scheduler placeholder) forwarding to the agent.

Phase 0 surface:
  - any text message  -> default-tier turn (capture / chat)
  - /spec <idea>      -> strong-tier turn that writes a spec to vault/01-projects/
  - inline buttons    -> approve/deny writes outside the auto-approve allowlist

Access is restricted to TELEGRAM_ALLOWED_USER_IDS. The scheduler is wired but
idle until Phase 4.
"""
from __future__ import annotations

import logging
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

from . import config, loop, memory, providers
from .loop import TurnResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("personal-ai")

# In-process store of turns waiting on approval:
# token -> (session_id, resume_messages, tier, pending_call_ids)
_PENDING: dict[str, tuple[str, list, str, list[str]]] = {}

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


async def _deliver(update: Update, result: TurnResult) -> None:
    """Send a TurnResult to the user, rendering an approval prompt if needed."""
    if result.needs_approval:
        token = uuid.uuid4().hex[:12]
        call_ids = [r.tool_call_id for r in result.approvals]
        _PENDING[token] = (_session_id(update), result.resume_messages, "default", call_ids)
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
        "Personal AI online. Send an idea to capture it, or /spec <idea> for a full spec."
    )


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    text = update.effective_message.text or ""
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        result = await loop.run_turn(_session_id(update), text, tier="default")
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
    await _deliver(update, result)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    query = update.callback_query
    await query.answer()
    action, _, token = query.data.partition(":")
    pending = _PENDING.pop(token, None)
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
    await _deliver(update, result)


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
    if not config.TELEGRAM_ALLOWED_USER_IDS:
        log.warning("TELEGRAM_ALLOWED_USER_IDS is empty — the bot is OPEN to anyone.")
    memory.init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("spec", on_spec))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Scheduler is wired now, idle until Phase 4 adds jobs.
    scheduler = AsyncIOScheduler()
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    return app


def main() -> None:
    app = build_app()
    log.info("Personal AI starting (kill_switch=%s)", config.KILL_SWITCH)
    app.run_polling()


if __name__ == "__main__":
    main()
