"""The deterministic morning briefing."""
from __future__ import annotations

from datetime import date

from agent import briefing


def test_job_next_actions_excludes_terminal(sandbox):
    (sandbox / "vault" / "crm" / "applications.md").write_text(
        "# Job applications\n\n"
        "| Company | Role | Status | Applied | Next action | Link |\n"
        "|---|---|---|---|---|---|\n"
        "| Acme | Staff Eng | applied | 2026-06-28 | follow up Friday | x |\n"
        "| Globex | SRE | interview | 2026-06-20 | prep sys design | |\n"
        "| Initech | Dev | rejected | 2026-06-10 | — | |\n"
    )
    actions = briefing._job_next_actions()
    assert any("Acme" in a for a in actions)
    assert any("Globex" in a for a in actions)
    assert not any("Initech" in a for a in actions)  # terminal status excluded


def test_build_reports_inbox_backlog_and_persists_journal(sandbox):
    (sandbox / "vault" / "00-inbox" / "a.md").write_text("note a")
    (sandbox / "vault" / "00-inbox" / "b.md").write_text("note b")
    text = briefing.build()
    assert "2 note(s) in the inbox" in text
    page = sandbox / "vault" / "journal" / f"{date.today().isoformat()}.md"
    assert page.exists() and page.read_text().startswith("# Briefing")


def test_build_all_clear(sandbox):
    text = briefing.build()
    assert "All clear" in text
