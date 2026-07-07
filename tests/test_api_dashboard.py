"""The PWA read-only dashboard (slice P2): bootstrap, finance, notes."""
from __future__ import annotations

import csv

import pytest
from fastapi.testclient import TestClient

from agent import finance, retrieval, spend
from api import auth
from api.server import build_api


@pytest.fixture
def client(sandbox, monkeypatch):
    auth.init_db()
    spend.init_db()
    retrieval.init_db()
    ledger = sandbox / "finance" / "transactions" / "ledger.csv"
    monkeypatch.setattr(finance, "LEDGER_PATH", ledger)
    with open(ledger, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=finance.LEDGER_FIELDS)
        w.writeheader()
        w.writerows([
            {"id": "a1", "date": "2026-07-01", "description": "WHOLE FOODS",
             "amount": "-82.14", "category": "groceries", "account": "chase", "source": "t"},
            {"id": "a2", "date": "2026-07-03", "description": "PAYROLL",
             "amount": "4200.00", "category": "income", "account": "chase", "source": "t"},
            {"id": "a3", "date": "2026-06-11", "description": "STARBUCKS",
             "amount": "-6.40", "category": "dining", "account": "chase", "source": "t"},
        ])
    c = TestClient(build_api())
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session())
    return c


def test_bootstrap_requires_session(sandbox):
    auth.init_db()
    assert TestClient(build_api()).get("/api/bootstrap").status_code == 401


def test_bootstrap_shape(client):
    body = client.get("/api/bootstrap").json()
    assert {"status", "finance", "month"} <= body.keys()
    assert "spend_today_usd" in body["status"]


def test_finance_summary_month_filter(client):
    body = client.get("/api/finance/summary?month=2026-07").json()
    cats = {r["category"]: r["net"] for r in body["by_category"]}
    assert cats["groceries"] == pytest.approx(-82.14)
    assert "dining" not in cats  # June row filtered out


def test_finance_summary_rejects_bad_month(client):
    assert client.get("/api/finance/summary?month=notamonth").status_code == 400


def test_ledger_rows_and_category_filter(client):
    rows = client.get("/api/finance/ledger?category=dining").json()["rows"]
    assert len(rows) == 1 and rows[0]["description"] == "STARBUCKS"


def test_ledger_rejects_injection_shaped_category(client):
    res = client.get("/api/finance/ledger", params={"category": "x' OR '1'='1"})
    assert res.status_code == 400


def test_notes_dir_and_file(client, sandbox):
    note = sandbox / "vault" / "03-resources" / "espresso.md"
    note.write_text("# Espresso\n\nGrind finer when sour.\n- 18g in\n")
    body = client.get("/api/notes?path=vault/03-resources").json()
    assert body["type"] == "dir"
    assert {"name": "espresso.md", "dir": False} in body["entries"]
    body = client.get("/api/notes?path=vault/03-resources/espresso.md").json()
    assert body["type"] == "file" and "Grind finer" in body["content"]


def test_notes_refuses_escape_and_non_vault(client, sandbox):
    (sandbox / "agent").mkdir(exist_ok=True)  # exists, so only the guard can save us
    assert client.get("/api/notes?path=agent").status_code == 403
    assert client.get("/api/notes?path=vault/../agent").status_code == 403
    assert client.get("/api/notes", params={"path": "vault/../../etc/passwd"}).status_code == 403


def test_notes_search(client, sandbox):
    note = sandbox / "vault" / "03-resources" / "espresso.md"
    note.write_text("# Espresso\n\nGrind finer when sour.\n")
    retrieval.index_file("vault/03-resources/espresso.md")
    hits = client.get("/api/notes/search?q=espresso").json()["hits"]
    assert hits and hits[0]["path"] == "vault/03-resources/espresso.md"
