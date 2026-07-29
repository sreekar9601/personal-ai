# Command Center Plan — framing this project for the resume

*Goal: present (and finish) this repo as a **Personal Agentic Command Center**
— one agent brain, reachable as an installed iPhone app and a desktop web
dashboard, over a git-backed personal data plane. Three workstreams: product,
presentation (README/repo), and code. Written 2026-07-29.*

---

## 0. The story we are selling (get this straight first)

A resume project is judged in ~90 seconds: repo title → README hero →
screenshots → architecture diagram → code skim. The narrative that survives
that skim:

> **Personal Agentic Command Center** — a self-hosted, multi-surface AI agent
> I use daily. One brain (tool-using LLM agent with human-in-the-loop
> approvals), three surfaces (installed iPhone PWA, desktop dashboard,
> optional Telegram), one git-backed data plane (finance ledger, personal
> wiki, tasks, memory). Passkey-secured, budget-capped, self-improving, and
> deployed with merge-to-ship CI/CD.

What makes it credible rather than a toy:
- **In production**: it runs 24/7 and commits its own morning briefings
  (`vault/journal/`) — the git history *is* the uptime proof.
- **Real agentic patterns**: tool use, deferred human approvals, scheduled
  autonomy, a reflection loop that edits its own playbooks, tier-routed
  models with prompt caching and a daily budget guard.
- **Real engineering**: 80 tests, CI/CD, WebAuthn, CSP, path-traversal
  guards, spend accounting, volume-durable state.

Two truthful gaps between today's app and the "command center" claim — both
are product work below:
1. It is phone-first; there is no **desktop dashboard** experience yet.
2. The **Tasks tab is a placeholder** — a visible hole in any demo.

---

## 1. Product level

### 1.1 The Command Center home view (the money shot)
A new **Overview** tab — first screen after unlock, and the screenshot at the
top of the README:
- Today: spend so far vs budget (gauge), tasks due, inbox count.
- This month: spend by category (the existing bars), income vs spent.
- **Agent activity feed**: the last N meaningful agent actions (from the
  audit log + git log) — "logged expense", "synthesized 3 notes", "morning
  briefing" — with timestamps. Nothing says *agentic* like a visible trail of
  things it did while you slept.
- System health strip: uptime, last git sync, model tiers, kill-switch state.

### 1.2 Desktop dashboard (the "webapp" half of the claim)
Same app, responsive breakpoint (~768px):
- Bottom tab bar becomes a **left sidebar**; content area becomes a
  **two-column grid** (Overview: activity feed beside the money panels;
  Chat: conversation beside a context panel).
- Keyboard affordances: `/` focuses chat input, `1–5` switch views.
- This is CSS/layout work on the existing vanilla JS app — no framework
  migration, no new server code.

### 1.3 Tasks — fill the placeholder
The design already exists (PLAN.md §5): `vault/tasks.md` checkbox store,
deterministic `add_task / complete_task / list_tasks` tools, `/api/tasks`
CRUD, and a Tasks tab (due dates, add/complete, agenda grouping). The agent
files task-shaped captures automatically during synthesis. This closes the
last "coming soon" in the UI.

### 1.4 Demo mode (show it without doxxing yourself)
`DEMO_MODE=true`: seeds a plausible fake vault/ledger/tasks in a temp dir,
auth bypassed with a visible "DEMO" badge, all writes to the real repo
disabled. Purpose: screenshots, the README GIF, and a live link a recruiter
can click without touching your data. (Deploy as a second tiny Fly app, or
run locally just to capture media.)

### 1.5 Branding
Display name: **"Command Center"** (manifest short_name), README title
**Personal Agentic Command Center**. Keep the repo slug `personal-ai` or
rename to `agentic-command-center` — renaming reads better on a resume line;
GitHub redirects old URLs, but update `GIT_REMOTE_URL` on Fly if renamed.
**Decision needed (yours).**

---

## 2. Presentation level (README + repo as a landing page)

Rewrite README top-down for the 90-second skim:

1. **Hero**: title, one-line pitch, badges (CI, tests, license, Python),
   then a **side-by-side screenshot**: iPhone (Overview) + desktop (Overview).
2. **Demo GIF** (~20s): type "spent 450 on groceries" → ledger row appears →
   Money tab updates → approval card Approve → note lands in wiki.
3. **Architecture diagram** (mermaid): surfaces → FastAPI/PTB → agent core
   (tools, approval gate, budget guard) → git data plane → Anthropic/GitHub;
   scheduler + reflection loop as side rails.
4. **Feature grid** (6–8 cells, one line each): agentic core, HITL approvals,
   passkey auth, finance pipeline, knowledge engine, proactive jobs,
   self-improvement, cost engineering.
5. **Security model** and **Cost engineering** as first-class sections
   (they're differentiators, not footnotes).
6. **Tech stack** line: Python 3.12, Pydantic AI, FastAPI, WebAuthn, SQLite
   FTS5, DuckDB, Web Push (VAPID), Fly.io, GitHub Actions.
7. Quickstart / deploy / tests (existing content, tightened).
8. **"Built with AI, engineered by me"** honesty note — pairs well in 2026.

Repo hygiene for scrutiny:
- `LICENSE` (MIT), repo description + topics (`ai-agent`, `pwa`, `fastapi`,
  `webauthn`, `pydantic-ai`, `personal-finance`), pin the repo, social
  preview image = the hero screenshot.
- `docs/ARCHITECTURE.md`: the diagram plus a written tour (request lifecycle
  of one chat turn incl. approval + spend accounting; the git data plane;
  the two self-improvement channels). Interviewers click exactly one doc —
  make it this one.
- Screenshots/GIF under `docs/media/` (captured in demo mode).

**Resume bullets this supports** (tune numbers at capture time):
- *Built and operate a self-hosted agentic AI system (“Personal Agentic
  Command Center”): a tool-using LLM agent with human-in-the-loop approvals,
  serving an installed iOS PWA + desktop dashboard from one FastAPI/Python
  process; in production 24/7 on Fly.io.*
- *Designed a passkey (WebAuthn/Face ID) single-user auth model, strict-CSP
  frontend, path-traversal-guarded file APIs, and a daily LLM budget guard
  with per-model spend accounting.*
- *Engineered an agent cost/quality router (3 model tiers, prompt caching,
  bounded history) and a git-backed data plane where every agent action is a
  commit — 80+ tests, merge-to-deploy CI/CD.*
- *Implemented agentic self-improvement: scheduled reflection loop that
  authors its own skills/playbooks inside a write-approval sandbox.*

---

## 3. Code level (slices, in order)

| # | Slice | What ships | Size |
|---|---|---|---|
| C1 | **Tasks** | `agent/tasks.py` (parse/write `vault/tasks.md`), 3 agent tools, `/api/tasks` GET/POST/PATCH, Tasks tab UI; synthesis playbook routes task-shaped captures | ~1 day |
| C2 | **Activity feed API** | `/api/activity`: merged, de-noised timeline from `.data/audit.log` + git log (knowledge commits); typed entries (expense, note, synthesis, briefing, approval) | ~½ day |
| C3 | **Overview tab** | Command-center home: today/month panels, activity feed, health strip; extend `/api/bootstrap`; becomes default view | ~1 day |
| C4 | **Desktop layout** | ≥768px: sidebar nav, two-column grid, keyboard shortcuts; no framework change | ~1 day |
| C5 | **Branding** | Manifest/app title "Command Center", icon refresh, login screen copy | ~¼ day |
| C6 | **Demo mode** | `DEMO_MODE`: seeded fake data plane in temp dir, auth bypass + DEMO badge, writes to real repo hard-disabled | ~½–1 day |
| C7 | **README + docs** | Hero README rewrite, `docs/ARCHITECTURE.md`, mermaid diagrams, LICENSE, badges; capture screenshots + GIF in demo mode | ~1 day |
| C8 | **Repo meta** | Description/topics/social image/pin; optional repo rename (decision §1.5); resume bullets finalized with real numbers | ~¼ day |

Sequencing logic: C1–C4 make the product match the claim (no placeholder
tabs, real desktop dashboard), C5–C6 make it photogenic and safely shareable,
C7–C8 do the selling. Everything rides the existing stack — no rewrites, no
new services, no new costs.

**Definition of done**: a stranger opening the repo sees the hero screenshot
of a dashboard they can click into (demo link), an architecture diagram they
can follow, and a green CI badge; you get 3–4 defensible resume bullets and
an app whose every tab works.
