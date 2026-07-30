"""Demo mode (slice C6) — a safe, seeded copy of the system for sharing.

`DEMO_MODE=true` makes the process run against a **throwaway data plane** in a
temp directory, seeded with plausible fake data, with auth bypassed so anyone
with the link can look around. This exists so screenshots, a README GIF, and a
public demo link never touch the owner's real finances or notes.

Safety, in order of strength:
  1. `config.REPO_ROOT` and `config.DATA_DIR` are re-pointed at the temp tree
     *before* anything reads them, so every path-derived constant follows.
  2. `config.GIT_PUSH` is forced off — a demo can never publish anything.
  3. The API layer refuses enrollment/recovery in demo mode and stamps a DEMO
     badge into `/api/me` so the UI can label itself.

Call `activate()` once at startup, before init_db/reindex.
"""
from __future__ import annotations

import csv
import logging
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import config

log = logging.getLogger("personal-ai.demo")

_DIRS = (
    "vault/00-inbox", "vault/01-projects", "vault/03-resources", "vault/04-archive",
    "vault/journal", "vault/crm", "memory", "skills", "playbooks",
    "finance/transactions", "finance/imports", ".data",
)


def _iso(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def activate() -> Path:
    """Re-point config at a seeded temp repo and return its path."""
    root = Path(tempfile.mkdtemp(prefix="command-center-demo-"))
    for d in _DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    # 1. Re-point every path the app derives from config.
    config.REPO_ROOT = root
    config.VAULT_DIR = root / "vault"
    config.MEMORY_DIR = root / "memory"
    config.SKILLS_DIR = root / "skills"
    config.PLAYBOOKS_DIR = root / "playbooks"
    config.FINANCE_DIR = root / "finance"
    config.DATA_DIR = root / ".data"
    config.SESSION_DB = root / ".data" / "sessions.db"
    config.AGENT_MD = root / "AGENT.md"
    config.USER_MD = root / "memory" / "USER.md"
    config.MEMORY_MD = root / "memory" / "MEMORY.md"
    config.AUTO_APPROVE_WRITE_DIRS = [
        config.VAULT_DIR, config.SKILLS_DIR, config.PLAYBOOKS_DIR,
        config.MEMORY_DIR, config.FINANCE_DIR / "transactions",
    ]
    # 2. A demo can never push.
    config.GIT_PUSH = False

    _seed(root)
    log.warning("DEMO MODE: serving seeded fake data from %s (auth bypassed).", root)
    return root


def _seed(root: Path) -> None:
    """Write a plausible personal data plane: ledger, tasks, wiki, activity."""
    from . import audit, finance, tasks

    # Constitution + memory (the prompt reads these; keep them realistic).
    real_agent_md = config.CODE_ROOT / "AGENT.md"
    if real_agent_md.is_file():
        (root / "AGENT.md").write_text(real_agent_md.read_text())
    (root / "memory" / "USER.md").write_text(
        "# USER.md\n\n- **Name:** Sam (demo persona)\n"
        "- **Focused on:** shipping a side project, tracking spend\n"
        "- **Style:** brief, direct\n- **Time zone:** Asia/Kolkata\n"
    )
    (root / "memory" / "MEMORY.md").write_text(
        "# MEMORY.md — durable facts\n\n"
        "- Drinks light-roast espresso; dials in at 18g/36g\n"
        "- Prefers one-line confirmations over explanations\n"
        "- Rent is due on the 1st\n"
    )

    # Finance: a month of believable transactions.
    finance.LEDGER_PATH = root / "finance" / "transactions" / "ledger.csv"
    rows = [
        (_iso(0), "Blue Tokai coffee", -380, "dining"),
        (_iso(0), "Metro card top-up", -500, "transport"),
        (_iso(-1), "BigBasket groceries", -1450, "groceries"),
        (_iso(-2), "Swiggy dinner", -640, "dining"),
        (_iso(-3), "Uber to airport", -620, "transport"),
        (_iso(-4), "Amazon — desk lamp", -2199, "home"),
        (_iso(-6), "Salary", 85000, "income"),
        (_iso(-7), "Rent", -28000, "housing"),
        (_iso(-9), "Gym membership", -1800, "health"),
        (_iso(-12), "Kindle book", -299, "learning"),
        (_iso(-14), "Electricity bill", -1240, "utilities"),
        (_iso(-18), "Cinema", -700, "entertainment"),
    ]
    with open(finance.LEDGER_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=finance.LEDGER_FIELDS)
        w.writeheader()
        for i, (d, desc, amt, cat) in enumerate(rows, 1):
            w.writerow({
                "id": f"demo{i:03d}", "date": d, "description": desc,
                "amount": f"{amt:.2f}", "category": cat, "account": "demo",
                "source": "chat" if amt > -3000 else "import",
            })
    (root / "finance" / "categories.yaml").write_text(
        "groceries: [bigbasket, grocery]\ndining: [swiggy, coffee, restaurant]\n"
        "transport: [uber, metro, fuel]\nutilities: [electricity, internet]\n"
        "housing: [rent]\nhealth: [gym, pharmacy]\nincome: [salary]\n"
    )

    # Tasks.
    tasks.add_task("renew passport", due=_iso(-2), tag="errand")
    tasks.add_task("call the dentist", due=_iso(0), tag="health")
    tasks.add_task("review Q3 budget", due=_iso(3), tag="work")
    tasks.add_task("draft the launch post", due=_iso(6), tag="project")
    tasks.add_task("read the Karpathy post on agents")

    # Wiki + inbox + a project spec.
    (root / "vault" / "03-resources" / "espresso-dialing.md").write_text(
        "---\ntype: resource\ncreated: " + _iso(-5) + "\ntags: [coffee]\n---\n"
        "# Espresso dialing\n\nWhen the shot tastes sour, grind finer; when it\n"
        "tastes bitter or hollow, grind coarser.\n\n"
        "- Baseline: 18g in, 36g out, 27s\n- Light roasts want hotter water (94–96°C)\n\n"
        "Related: [[coffee-gear]]\n"
    )
    (root / "vault" / "03-resources" / "coffee-gear.md").write_text(
        "---\ntype: resource\ncreated: " + _iso(-5) + "\ntags: [coffee]\n---\n"
        "# Coffee gear\n\nNiche Zero grinder, Gaggia Classic with a PID.\n\n"
        "Related: [[espresso-dialing]]\n"
    )
    (root / "vault" / "03-resources" / "agent-architecture.md").write_text(
        "---\ntype: resource\ncreated: " + _iso(-3) + "\ntags: [ai, architecture]\n---\n"
        "# Agentic architecture notes\n\nA useful split: **judgement in the model,\n"
        "determinism in code.** The model decides *what* to do and supplies fields;\n"
        "code validates and writes.\n\n- Human-in-the-loop on anything irreversible\n"
        "- Tier the models: cheap for triage, strong for reasoning\n"
    )
    (root / "vault" / "00-inbox" / f"{_iso(0)}-newsletter-idea.md").write_text(
        "---\ntype: capture\ncreated: " + _iso(0) + "\nsource: pwa\n---\n"
        "Idea: a short weekly newsletter about what I actually shipped.\n"
    )
    (root / "vault" / "01-projects" / "launch-checklist.md").write_text(
        "---\ntype: spec\nstatus: draft\ncreated: " + _iso(-4) + "\n---\n"
        "# Launch checklist\n\n## Problem\nShipping quietly means nobody sees it.\n\n"
        "## Milestones\n1. Landing page\n2. Demo video\n3. Post\n"
    )
    (root / "vault" / "index.md").write_text(
        "# Index\n\n- `03-resources/espresso-dialing.md` — dialing in espresso\n"
        "- `03-resources/coffee-gear.md` — the grinder/machine setup\n"
        "- `03-resources/agent-architecture.md` — notes on agent design\n"
    )
    (root / "vault" / "journal" / f"{_iso(0)}.md").write_text(
        f"# Briefing — {_iso(0)}\n\n- ⚠️ Overdue:\n    - renew passport\n"
        "- 📌 Due today:\n    - call the dentist\n- 📥 1 note in the inbox\n"
    )
    (root / "vault" / "log.md").write_text(
        "# Agent action log\n\n"
        f"- {_iso(-1)}: synthesised 3 captures into 2 wiki pages\n"
        f"- {_iso(0)}: logged expense (Blue Tokai coffee)\n"
    )

    # Activity trail (what the Overview feed shows).
    for tool, args, status in [
        ("vault_write", {"rel_path": "vault/03-resources/agent-architecture.md"}, "[written]"),
        ("remember", {"fact": "drinks light-roast espresso"}, "[remembered]"),
        ("vault_move", {"src": "vault/00-inbox/coffee.md",
                        "dst": "vault/04-archive/coffee.md"}, "[moved]"),
        ("add_task", {"text": "call the dentist"}, "[added]"),
        ("log_expense", {"amount": 380, "description": "Blue Tokai coffee"}, "[logged]"),
        ("finance_query", {"sql": "SELECT category, SUM(amount) FROM ledger ..."}, "ok:8rows"),
    ]:
        audit.record(tool, args, status)

    # Some agent spend for today, so the cost meter shows a real reading.
    try:
        from . import spend

        spend.init_db()
        spend.record("anthropic:claude-sonnet-4-6", type("U", (), {
            "input_tokens": 386_000, "output_tokens": 21_400,
            "cache_read_tokens": 164_000, "cache_write_tokens": 8_200})())
    except Exception:  # seeding spend is cosmetic
        pass

    # A git history so the feed and /status have commits to show.
    try:
        for cmd in (["git", "init", "-q"],
                    ["git", "config", "user.email", "demo@command-center.local"],
                    ["git", "config", "user.name", "command-center"]):
            subprocess.run(cmd, cwd=root, check=True, capture_output=True)
        commits = [
            ("wiki synthesis: 2 pages, 3 captures", "vault/log.md"),
            ("finance: import transactions", "finance/transactions/ledger.csv"),
            ("tasks: add", "vault/tasks.md"),
            ("journal: morning briefing", f"vault/journal/{_iso(0)}.md"),
        ]
        for subject, _ in commits:
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", subject],
                cwd=root, check=True, capture_output=True,
            )
    except (OSError, subprocess.SubprocessError):  # git is optional for the demo
        log.info("demo seed: git unavailable, activity feed will use the audit log only")
