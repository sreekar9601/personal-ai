# personal-ai

A single personal agent over one git-backed knowledge repo, reachable via
Telegram. Model-agnostic (Pydantic AI), Obsidian as the editing surface.

**Phase 0 (this):** capture ideas + generate specs from your phone, with
approval-gated writes, SQLite+FTS memory, tier-routed models, and git as sync.

## Quickstart

1. **Install deps** (uv manages Python 3.12):
   ```bash
   uv sync
   ```
2. **Configure secrets:**
   ```bash
   cp .env.example .env
   ```
   Fill in `.env`:
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather).
   - `TELEGRAM_ALLOWED_USER_IDS` — your numeric id from
     [@userinfobot](https://t.me/userinfobot). **Set this** or the bot is open.
   - `ANTHROPIC_API_KEY` — pay-as-you-go key; set a spend cap in the console.
3. **Run:**
   ```bash
   uv run python -m agent.main
   ```
4. **Use it from Telegram:**
   - Send any text → it's captured as a note in `vault/00-inbox/`.
   - `/spec <idea>` → a full spec written to `vault/01-projects/` (strong tier).
   - Writes outside `vault/ skills/ playbooks/ memory/ finance/transactions/`
     trigger an Approve/Deny button — that's the safety gate, not a bug.

## Editing the vault

Open the `vault/` folder (not the repo root) as an Obsidian vault. Install the
Obsidian Git plugin to pull the agent's commits to your desktop.

## Switching models / providers

Edit `agent/models.yaml` — change `provider` and the three tier model strings.
No Python changes. (Set the matching provider API key in `.env`.)

## Safety model (Phase 0)

- **Kill switch:** `KILL_SWITCH=true` disables all writes + git push.
- **Approval gate:** writes outside the allowlist need a Telegram confirmation.
- **Path safety:** any path escaping the repo root is refused.
- **Audit:** every turn commits knowledge changes to git; `vault/log.md` logs actions.

See the master build plan for Phases 1–6 (knowledge engine, job search, finance,
proactive, self-improvement, hardening).
