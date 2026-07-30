"""Shared test fixtures.

The agent modules resolve their paths from agent.config at import time, so tests
that touch the filesystem build a throwaway repo tree and point the relevant
config/module constants at it. Nothing here needs network or a model.
"""
from __future__ import annotations

import pytest

from agent import config


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway repo root with the standard dirs, wired into config."""
    root = tmp_path
    for sub in ("vault/00-inbox", "vault/crm", "vault/journal", "vault/03-resources",
                "memory", "finance/imports", "finance/transactions", "skills", ".data"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "REPO_ROOT", root)
    monkeypatch.setattr(config, "VAULT_DIR", root / "vault")
    monkeypatch.setattr(config, "MEMORY_DIR", root / "memory")
    monkeypatch.setattr(config, "SKILLS_DIR", root / "skills")
    monkeypatch.setattr(config, "FINANCE_DIR", root / "finance")
    monkeypatch.setattr(config, "DATA_DIR", root / ".data")
    monkeypatch.setattr(config, "MEMORY_MD", root / "memory" / "MEMORY.md")
    monkeypatch.setattr(config, "SESSION_DB", root / ".data" / "sessions.db")
    monkeypatch.setattr(config, "AUTO_APPROVE_WRITE_DIRS", [
        root / "vault", root / "skills", root / "memory",
        root / "finance" / "transactions",
    ])
    monkeypatch.setattr(config, "KILL_SWITCH", False)

    # Module-level paths are bound at import time, so patching REPO_ROOT alone
    # would leave these pointing at the real repo (tests must never read or
    # write the developer's actual ledger).
    from agent import finance

    monkeypatch.setattr(
        finance, "LEDGER_PATH", root / "finance" / "transactions" / "ledger.csv"
    )
    monkeypatch.setattr(finance, "IMPORTS_DIR", root / "finance" / "imports")
    monkeypatch.setattr(
        finance, "PROCESSED_DIR", root / "finance" / "imports" / "processed"
    )
    monkeypatch.setattr(finance, "CATEGORIES_YAML", root / "finance" / "categories.yaml")
    return root
