# PLAN.md — Master build plan

*The roadmap from "Telegram capture bot" to a secure, self-improving personal AI.
Written 2026-07-04 against the Phase 0/1 codebase. The user's stated goals, in
their words:*

> A personal AI for myself, which is self-improving. If I give it an expense I
> made, it should automatically add it to an expense tracker, and when I open a
> dashboard all changes should reflect. If I give it an idea or a thought, it
> should help me with organization and clarity, todo lists, etc. It should be
> secure, and the main point of contact should be my phone.

---

## 1. Where the project stands

**Working today (Phases 0–1):**

- Telegram → single Pydantic AI agent (`agent/loop.py`), tier-routed models
  (`agent/models.yaml`), prompt caching on Anthropic.
- Capture-by-default into `vault/00-inbox/`, `/spec` for idea → spec,
  `/synthesize` to fold captures into a cross-linked wiki.
- SQLite FTS5 retrieval over the vault + past conversations; durable memory
  (`memory/USER.md`, `memory/MEMORY.md`) grown via the `remember` tool.
- Safety: repo-confined paths, write-approval gate outside the allowlist,
  kill switch, per-turn request ceiling, git commit per turn as audit trail.

**Missing against the stated goals:**

| Goal | Status |
|---|---|
| Expense → tracker automatically | Nothing exists. `finance/transactions/` is an empty dir. |
| Dashboard that reflects changes | Nothing exists. `dashboards/` is an empty dir. |
| Thoughts → organization, todos | Capture + synthesis exist; **no task/todo system at all**. |
| Phone as main contact | Telegram works for text; **no voice notes, no receipt photos**. |
| Self-improving | Agent *can* write `skills/`, but nothing ever loads or surfaces them. Scheduler runs zero jobs. No reflection loop. |
| Secure | Good foundation, but see the critical fixes below — including a data-loss bug in the deployment. |

---

## 2. Phase 2 — Critical fixes (do first, ~a day)

These are not features; they are things that will hurt you the first time they
fire.

### 2.1 Data durability on Fly (CRITICAL — silent data loss)
`fly.toml` mounts a volume at `/data` and the Dockerfile sets
`PERSONAL_AI_DATA=/data`, but `agent/config.py` never reads that variable:
`DATA_DIR` is hard-coded to `<repo>/.data`, and the repo itself lives in the
image at `/app`. **Every redeploy discards the vault, the git history, and the
SQLite databases.**

Fix:
- On startup, if `PERSONAL_AI_DATA` is set: clone/pull the knowledge repo into
  `/data/repo` (first boot clones from `origin`; later boots `git pull`), and
  point `REPO_ROOT`-derived paths and `SESSION_DB` there.
- Ship a GitHub deploy key (or fine-grained PAT) as a Fly secret so
  `GIT_PUSH=true` actually pushes — git push **is** the backup strategy, so it
  must work unattended.
- Add a startup self-check that refuses to boot read-write if the volume is
  expected but absent.

### 2.2 Fail closed when the allowlist is empty
Today an empty `TELEGRAM_ALLOWED_USER_IDS` means the bot is open to **anyone
on Telegram** who finds it, with write access to your vault and your API
budget. A log warning is not enough for something that holds personal
finances. Change to: hard exit unless `DEV_MODE=true` is explicitly set.

### 2.3 Persist pending approvals
`_PENDING` in `agent/main.py` is an in-process dict. A restart between
"approval requested" and "button tapped" silently loses the turn. Move pending
approvals into SQLite with an expiry; on `resume` after restart, reload from
there.

### 2.4 Bound conversation history
`memory.load_history()` returns the entire session history forever and feeds
it to every turn. Cost grows without bound and will eventually blow the
context window. Add windowing: keep the last N turns verbatim, and roll older
turns into a cheap-tier summary stored per session.

### 2.5 Daily spend ceiling
`MAX_TURNS` caps one turn; nothing caps a day. Record per-turn token usage
(Pydantic AI exposes it on `run_result.usage()`) into SQLite, and have the bot
refuse politely once a configurable daily budget is hit. This is the "can't
wake up to a $400 bill" control.

---

## 3. Phase 3 — Finance: the expense tracker (highest stated value)

Design principle: **capture must be zero-friction from the phone; storage must
be deterministic and dashboard-readable.** The model parses; code writes.

### 3.1 Data model — a plain-text ledger in git
Monthly CSV files, one row per transaction:

```
finance/transactions/2026-07.csv
id,date,amount,currency,category,merchant,description,source
a1b2c3,2026-07-04,450.00,INR,groceries,BigBasket,weekly veg run,telegram
```

Why CSV-in-git and not SQLite: it rides the existing git sync/audit/backup
path, it's human-auditable and Obsidian-viewable, diffs are meaningful, and
the dashboard can consume it with zero server round-trips. A SQLite mirror
(same pattern as `vault_fts`) is rebuilt from the CSVs on startup for fast
querying by the agent.

Categories live in `finance/categories.md` — a plain list the **agent may
extend** (it's inside the auto-approve zone), which is a small, safe instance
of self-improvement: your taxonomy adapts to how you actually spend.

### 3.2 Tools (deterministic writes, model only parses)
- `log_expense(amount, currency, category, merchant, description, date?)` —
  appends one row, returns a one-line confirmation with the category chosen.
  ID generated in code; date defaults to today; amount validated in code.
- `query_expenses(month?, category?, merchant?, text?)` — totals + rows from
  the SQLite mirror, so "what did I spend on food in June?" is grounded, not
  guessed.
- `correct_expense(id, field, value)` — edits by rewriting the CSV row; the
  git diff is the audit trail. ("that wasn't groceries, that was dining out")

### 3.3 Flows from the phone
- **Text**: "spent 450 on groceries at BigBasket" → cheap-tier parse →
  `log_expense` → "✓ ₹450 · groceries · BigBasket · today". No approval prompt
  (inside the allowlist), no friction.
- **Receipt photos**: Telegram photo handler → image goes to a default-tier
  vision call → extract amount/merchant/date/line-items → `log_expense` →
  confirmation with what it read, so you can correct in one message. This is
  the single biggest real-world friction remover for expense tracking.
- **Voice notes**: Telegram voice handler → transcription (provider audio
  model or Whisper API) → then treated exactly like a text message. Serves
  *both* expense capture and idea capture while walking.
- `/month` — spend summary for the current month, by category, as text +
  a rendered chart image (see 4.1) right in Telegram.

### 3.4 Recurring & imports (later slice)
- `finance/recurring.md`: known subscriptions/rent; a scheduled job posts them
  on their due date for one-tap confirm.
- `finance/imports/`: drop a bank-statement CSV, `/import` maps columns and
  dedupes against the ledger. Keep this **after** manual capture works — value
  comes from the habit loop first.

---

## 4. Phase 4 — The dashboard

Phone-first means the dashboard has two tiers:

### 4.1 In-chat dashboard (Telegram, instant)
`/dash` renders a chart image (matplotlib, no server needed) + text summary:
month-to-date by category vs. last month, biggest merchants, remaining budget
if one is set. This covers 90% of "how am I doing?" moments and works from
anywhere your phone works.

### 4.2 Full dashboard (HTML, auto-updating)
A **single self-contained HTML file** (`dashboards/index.html`) with the
transaction data inlined as JSON and charts rendered client-side.
Regenerated by deterministic code (not the model) after every finance write,
committed like everything else.

Two ways to open it, in order of preference:
1. **Synced repo**: Obsidian Git (or any `git pull`) on desktop → open the
   file. Zero servers, zero new attack surface, changes reflect on next pull.
2. **Served by the Fly app** (optional, when you want it on the phone
   browser): add a minimal HTTP endpoint with **BasicAuth over a Fly secret +
   an unguessable path token**. This is the only change that opens a port —
   keep it off until wanted, and document it as such in `fly.toml`.

Also generate `dashboards/tasks.html` (§5) and later a weekly-review page —
same pipeline, one pattern.

---

## 5. Phase 5 — Todos, organization & clarity

### 5.1 Task store
`vault/tasks.md` — markdown checkboxes with metadata, Obsidian-native:

```
- [ ] renew passport 📅 2026-07-20 #errand
- [x] email landlord ✅ 2026-07-02
```

Tools: `add_task(text, due?, tag?)`, `complete_task(match)`, `list_tasks(filter?)` —
deterministic file edits, same pattern as expenses. The FTS index already
covers `vault/`, so tasks are searchable for free.

### 5.2 Thought → clarity behaviors (prompt + playbook work, not code)
- Extend the capture playbook: when a capture **contains an implicit action**
  ("I should really call the dentist"), the agent files the note *and* offers
  the task in the same one-line reply: "Filed. Add 'call dentist' to tasks?"
- `/clarify <topic or note>` — a strong-tier pass over one thought or a cluster
  of related captures: what is actually being decided, options, a recommended
  next action, filed under `vault/01-projects/` when it's becoming real.
- `/agenda` — today: due/overdue tasks, calendar-free daily brief (until a
  calendar source exists), yesterday's spend one-liner.

### 5.3 Synthesis learns about tasks
Update `playbooks/synthesis.md`: captures that are *tasks in disguise* get
routed to `vault/tasks.md` during the synthesis pass instead of becoming wiki
pages. The inbox drains into **three** places now: wiki (knowledge), tasks
(actions), memory (facts about you).

---

## 6. Phase 6 — Proactive: the scheduler earns its keep

All of these are existing capabilities put on a clock (APScheduler is already
wired and idle). Each job is a normal agent turn with a directive — same
pattern as `/synthesize` — so all safety gates apply unchanged.

- **Nightly synthesis** (e.g. 03:00): drain the inbox automatically. The
  capture→wiki loop stops depending on you remembering to run it.
- **Morning brief** (e.g. 07:30): `/agenda` pushed to you — tasks due, spend
  yesterday, anything the reflection job flagged.
- **Weekly review** (Sunday): spend vs. last week by category, tasks completed
  vs. added, inbox health, wiki pages touched — pushed as a message + a
  `dashboards/weekly-review` page.
- **Recurring-expense prompts** (§3.4) on their due dates.

One new safety rule: scheduled runs never get approval-gated writes — if a
job's turn would need approval, it posts the request to Telegram and stops,
rather than stalling silently.

---

## 7. Phase 7 — Self-improvement, made real

The constitution already defines the safe channel (agent may edit
`skills/`/`playbooks/`; code is PR-gated). What's missing is the **loop**:

1. **Skills actually load.** At prompt-assembly time, list every file in
   `skills/` and `playbooks/` with its `when_to_use` frontmatter in the system
   prefix (names only — bodies pulled via `vault_read` on demand, keeping the
   cacheable prefix small). Today a skill the agent writes is a skill nobody
   ever reads.
2. **Feedback capture.** `/feedback <text>` and a 👍/👎 reaction handler append
   to `vault/feedback.md` with a pointer to the turn. Cheap to build; this is
   the training signal.
3. **Weekly reflection job** (scheduler): strong-tier pass over
   `vault/log.md`, `vault/feedback.md`, and denied approvals from the past
   week → proposes concrete playbook/skill edits (auto-approve zone, applied
   immediately) and files anything requiring code changes as a note in
   `vault/01-projects/agent-improvements.md` for you to turn into a PR (or
   hand to Claude Code).
4. **Category/heuristic drift.** Finance categories (§3.1) and capture
   heuristics live in agent-editable files, so day-to-day behavior tunes
   itself without touching Python.

This gives a genuine improvement flywheel with a hard boundary: *behavior*
improves autonomously, *capability* (code) improves only through review.

---

## 8. Phase 8 — Security hardening (ongoing, but concretely)

Beyond the Phase 2 critical fixes:

- **Approval UX**: per-write Approve/Deny buttons instead of all-or-nothing
  batches; show full content for short writes, not a 200-char preview.
- **Telegram output escaping**: approval summaries interpolate model/user text
  into Markdown — switch to MarkdownV2 with proper escaping (malformed
  entities can make messages silently fail to render).
- **Untrusted-content envelope**: when external sources arrive (bank CSVs,
  receipt OCR text, later email), wrap them in explicit
  `<untrusted>` markers in the prompt, reinforcing the instruction/data
  boundary the constitution already states.
- **Repo hygiene guard**: refuse `vault_write` of content matching secret
  patterns (API keys, card numbers) — the vault is git-pushed; secrets must
  never land in it.
- **Backups beyond git**: nightly `sqlite3 .backup` of the session DB to the
  Fly volume; the vault is covered by push (§2.1).
- **Tests + CI**: the repo has zero tests. Minimum viable: path-escape tests
  for `hooks.py`, approval-gate tests for `loop.py`'s tools, ledger
  read/write round-trip, FTS query sanitization. One GitHub Actions workflow.
  This is a *security* item: the approval gate is only as real as the tests
  that pin it.

---

## 9. End-to-end deployment: from merged PRs to a live bot

Goal: **after the PRs are merged, one short bootstrap (secrets can't live in
git) puts the bot on your phone — and every merge after that deploys itself.**

### 9.1 Target architecture at go-live

```
Your phone (Telegram)
      │  long-polling (no inbound port, no public URL)
      ▼
Fly.io machine  ──  /data volume (persistent)
  agent.main          ├── repo/        ← git clone of this repo (vault, finance, memory)
  APScheduler         └── sessions.db  ← SQLite (history, FTS, approvals, spend)
      │
      ├── Anthropic API (tier-routed models)
      └── GitHub (push after every knowledge commit = offsite backup + Obsidian sync)
```

The bot polls Telegram outward, so the machine exposes **no public HTTP
service** — nothing to scan, nothing to firewall — until/unless the optional
dashboard endpoint (§4.2) is enabled.

### 9.2 Code changes required (part of the PRs, not manual work)

1. **Startup bootstrap** (`agent/bootstrap.py`, called first in `main()`):
   - If `PERSONAL_AI_DATA` is set: ensure `/data/repo` exists — first boot
     clones from `GIT_REMOTE_URL` using the deploy key; later boots
     `git pull --ff-only`. All paths in `config.py` derive from this root.
   - If unset (local dev): run in-place from the working copy, exactly as today.
   - Verify writable data dir, run `init_db()` + `reindex_vault()`, then start
     polling. Fail loudly (and exit non-zero so Fly restarts/alerts) if the
     volume or a required secret is missing.
2. **Deploy key auth for git**: mount `GIT_SSH_KEY` (Fly secret) to a file at
   boot, set `GIT_SSH_COMMAND`; repo gets a single-repo, write-scoped deploy
   key — not your account credentials.
3. **CI/CD workflow** (`.github/workflows/deploy.yml`):
   - On PR: `uv sync && pytest` + `ruff` (the Phase 8 tests).
   - On merge to `main`: `flyctl deploy --remote-only` using a `FLY_API_TOKEN`
     repo secret. **This is what makes "merge → live" true** — after the
     one-time bootstrap, you never run a deploy command again.
4. **`/status` command**: replies with uptime, model tiers, last git push
   time, today's token spend vs. budget, pending inbox count. Your one-glance
   health check from the phone.

### 9.3 One-time bootstrap (~10 minutes, done once, before or after merging)

Secrets can never be in the repo, so this part is manual by design:

```bash
# 0. Prereqs (one-time accounts/keys)
#    - Telegram: @BotFather → create bot → token; @userinfobot → your numeric id
#    - Anthropic: pay-as-you-go API key, spend cap set in console
#    - GitHub: deploy key (write) added to this repo
#    - Fly.io account + flyctl installed

# 1. Create the app and the persistent volume
fly launch --no-deploy          # uses the checked-in fly.toml
fly volumes create personal_ai_data --size 1 --region iad

# 2. Set secrets (never in git)
fly secrets set \
  TELEGRAM_BOT_TOKEN=... \
  TELEGRAM_ALLOWED_USER_IDS=<your numeric id> \
  ANTHROPIC_API_KEY=... \
  GIT_REMOTE_URL=git@github.com:sreekar9601/personal-ai.git \
  GIT_SSH_KEY="$(cat deploy_key)" \
  DAILY_BUDGET_USD=5

# 3. Add FLY_API_TOKEN to GitHub repo secrets (enables auto-deploy on merge)
fly tokens create deploy | gh secret set FLY_API_TOKEN

# 4. First deploy (every later deploy happens automatically on merge)
fly deploy
```

**Local-first alternative** (no Fly at all): run `uv sync && uv run python -m
agent.main` on any always-on machine (old laptop, home server) with the same
`.env`. Everything in this plan works identically; Fly only buys you
"always on without owning hardware".

### 9.4 Go-live acceptance checklist

Run through this from your phone the day it ships — it doubles as the smoke
test for every future deploy:

- [ ] `/start` answers; a stranger's account gets silence (allowlist works).
- [ ] Send a thought → filed to `vault/00-inbox/`, one-line confirmation.
- [ ] "spent 120 on coffee" → `✓ ₹120 · dining · today`; row visible in
      `finance/transactions/<month>.csv` on GitHub within a minute (push works).
- [ ] Send a receipt photo → parsed expense, correct amount.
- [ ] `/dash` → chart image + month summary.
- [ ] "add task: renew passport by July 20" → appears in `vault/tasks.md`.
- [ ] Ask the bot to write outside the allowlist → Approve/Deny buttons
      appear; Deny leaves no file behind.
- [ ] `/status` → healthy; token spend shown.
- [ ] `fly machine restart` → conversation context and pending approvals
      survive; vault intact (volume + persisted state work).
- [ ] Next morning: the scheduled brief arrives unprompted.

### 9.5 Operating it (steady state)

- **Update flow**: merge PR → CI tests → auto-deploy → `/status` to confirm.
  Rollback is `fly releases` + `fly deploy --image <previous>`.
- **Observability**: `fly logs` for the raw stream; set `LOGFIRE_TOKEN` for
  traces + per-turn cost. The daily budget guard (§2.5) is the hard backstop.
- **Backups**: every knowledge change is committed and pushed (§2.1) — GitHub
  *is* the offsite backup; nightly SQLite `.backup` to the volume (§8) covers
  session state. Restore = new volume + clone + redeploy.
- **Editing from desktop**: open `vault/` in Obsidian with the Git plugin;
  your edits push, the bot's bootstrap pulls on restart (and a scheduled
  `git pull` keeps a long-running machine fresh).

---

## 10. Phase 10 — the personal app (iPhone PWA)

The long-term surface: an installable, passkey-locked web app served by the
same Fly machine — chat, money, tasks, notes, and status as tabs, with Web
Push for the proactive messages. It closes the Telegram privacy gap (traffic
goes phone → your server only; even push payloads are E2E-encrypted) and is
the expansion chassis for every future domain: one new tab + one new API
router per domain, same brain underneath.

Full design — architecture, iOS constraints, auth model, API surface, build
slices P1–P6 — lives in **`docs/PWA-DESIGN.md`**. Telegram stays the capture
channel until slice P3 proves the PWA chat is strictly nicer, then gets
demoted to fallback.

---

## 11. Sequencing

| Order | Phase | Why this order | Rough size |
|---|---|---|---|
| 1 | **2. Critical fixes** | Data-loss bug + open-bot risk; everything else builds on a durable base | ~1 day |
| 2 | **9. Deployment** (bootstrap, deploy key, CI/CD, `/status`) | Gets a real bot on your phone immediately; every later merge auto-ships | ~1 day + 10-min manual bootstrap |
| 3 | **3. Finance core** (text capture, ledger, `/month`) | Your #1 stated ask; establishes the deterministic-tool pattern | ~2–3 days |
| 4 | **4.1 + receipt photos + voice** | Makes phone capture genuinely zero-friction; dashboard-in-chat lands early | ~2 days |
| 5 | **5. Tasks + clarity flows** | Second stated ask; mostly reuses the ledger pattern | ~1–2 days |
| 6 | **6. Scheduler jobs** | Compounds everything above; small code, big felt value | ~1 day |
| 7 | **4.2 HTML dashboard** | Nice-to-have once in-chat dashboard proves the data model | ~1 day |
| 8 | **7. Self-improvement loop** | Needs feedback data flowing first | ~2 days |
| 9 | **8. Hardening + tests** | Interleave throughout; finish before adding email/calendar sources | ongoing |

Each slice ships independently and is usable the day it lands — with
deployment second in line, **you are talking to the live bot from slice 2
onward**, and every subsequent merge to `main` reaches your phone
automatically (§9.2.3). After the final PR merges, the go-live checklist
(§9.4) is the definition of done: run it once from Telegram and the system
described at the top of this document is the system you're holding.
