# personal-ai

A single personal agent over one git-backed knowledge repo, reachable via
Telegram. Model-agnostic (Pydantic AI), Obsidian as the editing surface.

It captures ideas, synthesises them into a personal wiki, tracks a job search,
answers questions about your spending, briefs you each morning, and improves its
own playbooks — all over plain files in one git repo, with approval-gated writes.

**Build phases (all shipped):**

| Phase | What it adds |
|---|---|
| 0 — core | Capture + spec writing, approval-gated writes, SQLite+FTS memory, tier-routed models, git as sync. |
| 1 — knowledge engine | Wiki **synthesis loop**, **keyword retrieval** (FTS over the vault), active **memory layer**. |
| 2 — job search | File-based CRM + application tracker, resume/cover tailoring. |
| 3 — finance | CSV import → categorised ledger → **DuckDB** spending queries. |
| 4 — proactive | Scheduled nightly synthesis + a morning **briefing** on Telegram. |
| 5 — self-improvement | A **reflection loop** that writes its own reusable skills. |
| 6 — hardening | Content guards, an audit trail, and a pytest suite. |

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
4. **Use it from Telegram** — send any text to capture it (questions get answered,
   grounded in the vault), or use a command:

   | Command | Does |
   |---|---|
   | `/spec <idea>` | Write a full spec to `vault/01-projects/` (strong tier). |
   | `/synthesize` | Fold inbox captures into the `vault/03-resources/` wiki. |
   | `/job <text>` | Track an application / status / prep in the CRM. |
   | `/import` | Import new CSVs from `finance/imports/` into the ledger. |
   | `/finance [YYYY-MM]` | Spending summary by category. |
   | `/briefing` | The morning briefing on demand. |
   | `/reflect` | Run a self-improvement pass over recent activity. |

   Writes outside `vault/ skills/ playbooks/ memory/ finance/transactions/`
   trigger an Approve/Deny button — that's the safety gate, not a bug.

## How it works

- **Knowledge engine (Phase 1).** `/synthesize` runs the "Karpathy loop": it
  folds raw captures into a small, durable wiki — one page per *topic*, merged
  and cross-linked, never deleted (processed captures move to `vault/04-archive/`).
  Every markdown file in `vault/` is indexed in SQLite FTS5; the `vault_search`
  tool grounds answers in what's written. `memory/USER.md` + `memory/MEMORY.md`
  ride in every prompt, and the agent grows `MEMORY.md` via the `remember` tool.
- **Job search (Phase 2).** The vault is the CRM: `vault/crm/applications.md` is
  a pipeline table, `vault/crm/<company>.md` a page each. Resume/cover tailoring
  works strictly from your real master resume — no fabrication.
- **Finance (Phase 3).** Drop bank/card CSVs in `finance/imports/` and `/import`:
  columns are detected, amounts normalised (spend<0, income>0), transactions
  categorised by `finance/categories.yaml` rules and de-duped into
  `finance/transactions/ledger.csv`. The `finance_query` tool answers money
  questions with read-only DuckDB SQL. Raw exports never enter git.
- **Proactive (Phase 4).** The scheduler runs a nightly synthesis pass and a
  morning briefing (inbox backlog, job next-actions, month-to-date spend) pushed
  to Telegram. Configure with `PROACTIVE_ENABLED` / `*_HOUR` in `.env`.
- **Self-improvement (Phase 5).** `/reflect` reviews recent activity and writes
  one reusable skill into `skills/` (or sharpens a playbook). It can touch
  `skills/` and `playbooks/` but never `agent/` code — that stays PR-gated.

## Editing the vault

Open the `vault/` folder (not the repo root) as an Obsidian vault. Install the
Obsidian Git plugin to pull the agent's commits to your desktop.

## Switching models / providers

Edit `agent/models.yaml` — change `provider` and the three tier model strings.
No Python changes. (Set the matching provider API key in `.env`.)

## Safety model

- **Kill switch:** `KILL_SWITCH=true` disables all writes + git push.
- **Fail-closed access:** startup aborts if `TELEGRAM_ALLOWED_USER_IDS` is empty
  (set `DEV_MODE=true` to deliberately run open, local dev only).
- **Daily budget:** `DAILY_BUDGET_USD` caps estimated model spend per day
  (pricing in `agent/models.yaml`); the bot declines politely once it's hit.
- **Approval gate:** writes outside the allowlist need a Telegram confirmation.
  Pending approvals are persisted, so they survive a restart.
- **Path safety:** any path escaping the repo root is refused.
- **Content guards (Phase 6):** oversized writes and private-key material are
  refused outright, even inside the auto-approve zone.
- **Read-only finance:** `finance_query` rejects anything but a single SELECT/WITH.
- **Audit:** every turn commits knowledge changes to git and logs to
  `vault/log.md`; side-effectful tool calls also append to `.data/audit.log`.

## Deploy (Fly.io)

See `PLAN.md` §9 for the full path. Short version: the volume at `/data` holds
a git clone of this repo (the knowledge) plus sqlite; `agent/bootstrap.py`
clones it on first boot and pulls on later boots. One-time setup:

```bash
fly launch --no-deploy
fly volumes create personal_ai_data --size 1 --region iad
fly secrets set TELEGRAM_BOT_TOKEN=... TELEGRAM_ALLOWED_USER_IDS=<your id> \
    ANTHROPIC_API_KEY=... DAILY_BUDGET_USD=5 \
    GIT_REMOTE_URL=git@github.com:<you>/personal-ai.git \
    GIT_SSH_KEY="$(cat deploy_key)"
fly tokens create deploy | gh secret set FLY_API_TOKEN   # merge -> auto-deploy
fly deploy                                               # first deploy only
```

After that, every merge to `main` tests and deploys itself
(`.github/workflows/deploy.yml`). `/status` in Telegram shows uptime, spend
vs. budget, inbox size, and the last knowledge commit.

## Tests

```bash
uv run --group dev pytest
```

Covers path safety + content guards, vault retrieval, the memory layer, finance
import/categorisation/query guards, and the briefing — no network or model calls.
