"""The active memory layer: durable-fact recording."""
from __future__ import annotations

from agent import memory


def test_add_fact_replaces_placeholder(sandbox):
    config_md = sandbox / "memory" / "MEMORY.md"
    config_md.write_text("# MEMORY.md\n\n- (no durable facts yet)\n")
    out = memory.add_fact("Prefers brief, direct replies")
    assert out.startswith("[remembered]")
    text = config_md.read_text()
    assert "(no durable facts yet)" not in text
    assert "- Prefers brief, direct replies" in text


def test_add_fact_dedupes(sandbox):
    (sandbox / "memory" / "MEMORY.md").write_text("# MEMORY.md\n")
    assert memory.add_fact("Time zone is US Eastern").startswith("[remembered]")
    assert memory.add_fact("Time zone is US Eastern").startswith("[known]")
    body = (sandbox / "memory" / "MEMORY.md").read_text()
    assert body.count("Time zone is US Eastern") == 1


def test_add_fact_normalises_leading_dash(sandbox):
    (sandbox / "memory" / "MEMORY.md").write_text("# MEMORY.md\n")
    memory.add_fact("- already a bullet")
    assert "- already a bullet" in (sandbox / "memory" / "MEMORY.md").read_text()


def test_add_fact_blocked_by_kill_switch(sandbox, monkeypatch):
    from agent import config
    monkeypatch.setattr(config, "KILL_SWITCH", True)
    assert memory.add_fact("x").startswith("[blocked]")
