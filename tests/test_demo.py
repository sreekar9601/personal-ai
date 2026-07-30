"""Demo mode (slice C6): seeded temp data plane, auth bypass, write protection."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent import bootstrap, config, demo, finance, tasks
from api import auth
from api.server import build_api


@pytest.fixture
def demo_root(monkeypatch, tmp_path):
    """Activate demo mode against a throwaway tree, restoring config after."""
    saved = {
        name: getattr(config, name)
        for name in (
            "REPO_ROOT", "VAULT_DIR", "MEMORY_DIR", "SKILLS_DIR", "PLAYBOOKS_DIR",
            "FINANCE_DIR", "DATA_DIR", "SESSION_DB", "AGENT_MD", "USER_MD",
            "MEMORY_MD", "AUTO_APPROVE_WRITE_DIRS", "GIT_PUSH",
        )
    }
    saved_ledger = finance.LEDGER_PATH
    monkeypatch.setattr(config, "DEMO_MODE", True)
    root = demo.activate()
    yield root
    for name, value in saved.items():
        setattr(config, name, value)
    finance.LEDGER_PATH = saved_ledger


def test_activate_repoints_paths_off_the_real_repo(demo_root):
    real = config.CODE_ROOT
    assert config.REPO_ROOT == demo_root
    assert demo_root != real
    assert config.VAULT_DIR.is_relative_to(demo_root)
    assert config.DATA_DIR.is_relative_to(demo_root)
    assert config.SESSION_DB.is_relative_to(demo_root)
    for d in config.AUTO_APPROVE_WRITE_DIRS:
        assert d.is_relative_to(demo_root)


def test_demo_can_never_push(demo_root):
    assert config.GIT_PUSH is False


def test_seed_creates_a_believable_data_plane(demo_root):
    rows = finance._read_ledger()
    assert len(rows) >= 10
    assert any(float(r["amount"]) > 0 for r in rows)   # income
    assert any(float(r["amount"]) < 0 for r in rows)   # spend
    open_tasks = tasks.list_tasks()
    assert len(open_tasks) >= 4
    assert any(t.due and t.due < "9999" for t in open_tasks)
    assert (demo_root / "vault" / "03-resources" / "espresso-dialing.md").is_file()
    assert (demo_root / "vault" / "index.md").is_file()
    assert (demo_root / "memory" / "MEMORY.md").is_file()
    assert (demo_root / ".data" / "audit.log").is_file()


def test_seeded_activity_feed_is_populated(demo_root):
    from agent import activity

    events = activity.recent()
    kinds = {e["kind"] for e in events}
    assert {"expense", "task", "memory", "note"} <= kinds


def test_bootstrap_skips_env_checks_in_demo(demo_root, monkeypatch):
    """No Telegram, no volume, no allowlist — a demo still boots."""
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", set())
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEPLOYED", True)
    bootstrap.ensure_environment()  # must not raise


# --- API behaviour ------------------------------------------------------------------
def test_api_open_and_badged_in_demo(demo_root):
    auth.init_db()
    from agent import spend
    spend.init_db()
    client = TestClient(build_api())  # note: no session cookie set
    me = client.get("/api/me").json()
    assert me["demo"] is True and me["authenticated"] is True
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/api/bootstrap").status_code == 200


def test_enrollment_and_recovery_refused_in_demo(demo_root):
    auth.init_db()
    client = TestClient(build_api())
    assert client.post(
        "/api/webauthn/register/options", json={"token": "x"}
    ).status_code == 403
    assert client.post(
        "/api/webauthn/register/verify", json={"token": "x"}
    ).status_code == 403
    assert client.post("/api/webauthn/recover", json={"code": "x"}).status_code == 403


def test_normal_mode_still_gated(sandbox):
    """Sanity: without DEMO_MODE the API is closed (the bypass is not sticky)."""
    auth.init_db()
    assert config.DEMO_MODE is False
    assert TestClient(build_api()).get("/api/status").status_code == 401
