"""Slice P5: deterministic expense logging + the photo capture endpoint."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from agent import finance
from agent import loop as agent_loop
from api import auth
from api.server import PWA_SESSION, build_api


@pytest.fixture
def fin(sandbox, monkeypatch):
    monkeypatch.setattr(
        finance, "LEDGER_PATH", sandbox / "finance" / "transactions" / "ledger.csv"
    )
    cats = sandbox / "finance" / "categories.yaml"
    cats.write_text("groceries: [bigbasket]\ndining: [starbucks]\n")
    monkeypatch.setattr(finance, "CATEGORIES_YAML", cats)
    return sandbox


# --- finance.add_expense --------------------------------------------------------
def test_add_expense_logs_signed_and_categorised(fin):
    out = finance.add_expense(450, "BigBasket weekly veg", date_str="2026-07-05")
    assert out.startswith("[logged] spent 450.00 · groceries")
    rows = finance._read_ledger()
    assert rows[0]["amount"] == "-450.00"
    assert rows[0]["category"] == "groceries"
    assert rows[0]["date"] == "2026-07-05"


def test_add_expense_income_positive(fin):
    finance.add_expense(85000, "Salary", income=True, date_str="2026-07-01")
    assert finance._read_ledger()[0]["amount"] == "85000.00"


def test_add_expense_dedupes(fin):
    finance.add_expense(100, "Starbucks", date_str="2026-07-02")
    out = finance.add_expense(100, "Starbucks", date_str="2026-07-02")
    assert out.startswith("[known]")
    assert len(finance._read_ledger()) == 1


def test_add_expense_validates(fin):
    assert finance.add_expense(-5, "x").startswith("[refused]")
    assert finance.add_expense("abc", "x").startswith("[refused]")
    assert finance.add_expense(10, "  ").startswith("[refused]")


def test_add_expense_kill_switch(fin, monkeypatch):
    from agent import config
    monkeypatch.setattr(config, "KILL_SWITCH", True)
    assert finance.add_expense(10, "x").startswith("[blocked]")


# --- /api/capture/photo ------------------------------------------------------------
@pytest.fixture
def client(sandbox):
    auth.init_db()
    c = TestClient(build_api())
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session())
    return c


def _photo(name="r.jpg", content=b"\xff\xd8\xff fakejpeg", ctype="image/jpeg"):
    return {"file": (name, io.BytesIO(content), ctype)}


def test_photo_requires_session(sandbox):
    auth.init_db()
    c = TestClient(build_api())
    assert c.post("/api/capture/photo", files=_photo()).status_code == 401


def test_photo_rejects_non_image(client):
    res = client.post(
        "/api/capture/photo", files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")}
    )
    assert res.status_code == 415


def test_photo_runs_vision_turn(client, monkeypatch):
    seen = {}
    async def fake_run_turn(session_id, text, tier="default", directive=None, media=None):
        seen.update(session=session_id, directive=directive, media=media)
        return agent_loop.TurnResult(text="[logged] spent 380.00 · dining · Blue Tokai")
    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    out = client.post("/api/capture/photo", files=_photo()).json()
    assert out["type"] == "reply" and "380.00" in out["text"]
    assert seen["session"] == PWA_SESSION
    assert "RECEIPT" in seen["directive"]
    assert seen["media"][0][1] == "image/jpeg"
    assert seen["media"][0][0].startswith(b"\xff\xd8\xff")


def test_photo_size_cap(client):
    big = b"x" * (8 * 1024 * 1024 + 1)
    res = client.post("/api/capture/photo", files=_photo(content=big))
    assert res.status_code == 413
