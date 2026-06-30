"""Finance: import normalisation, categorisation, de-dup, read-only queries."""
from __future__ import annotations

import csv

import pytest

from agent import finance


@pytest.fixture
def fin(sandbox, monkeypatch):
    """Point the finance module at the sandbox + a small category ruleset."""
    monkeypatch.setattr(finance, "IMPORTS_DIR", sandbox / "finance" / "imports")
    monkeypatch.setattr(finance, "PROCESSED_DIR", sandbox / "finance" / "imports" / "processed")
    monkeypatch.setattr(finance, "LEDGER_PATH", sandbox / "finance" / "transactions" / "ledger.csv")
    cats = sandbox / "finance" / "categories.yaml"
    cats.write_text(
        "groceries: [whole foods]\n"
        "dining: [starbucks]\n"
        "income: [payroll]\n"
    )
    monkeypatch.setattr(finance, "CATEGORIES_YAML", cats)
    return sandbox


def _write_export(fin, name, rows, header=("Posted Date", "Description", "Debit", "Credit")):
    p = fin / "finance" / "imports" / name
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def test_import_normalises_categorises_and_signs(fin):
    _write_export(fin, "chase.csv", [
        ["05/03/2026", "WHOLE FOODS MARKET", "82.14", ""],
        ["05/01/2026", "ACME CORP PAYROLL", "", "4200.00"],
        ["05/10/2026", "RANDOM LOCAL SHOP", "19.99", ""],
    ])
    res = finance.import_new()
    assert res == {"blocked": False, "added": 3, "files": 1, "skipped": 0}
    rows = {r["description"]: r for r in finance._read_ledger()}
    assert rows["WHOLE FOODS MARKET"]["category"] == "groceries"
    assert rows["WHOLE FOODS MARKET"]["amount"] == "-82.14"   # spend negative
    assert rows["ACME CORP PAYROLL"]["amount"] == "4200.00"    # income positive
    assert rows["RANDOM LOCAL SHOP"]["category"] == "uncategorized"
    # ISO date normalisation
    assert rows["WHOLE FOODS MARKET"]["date"] == "2026-05-03"


def test_import_is_idempotent(fin):
    # The id hash includes the account (proxied by filename, by design), so the
    # guarantee is: re-importing the SAME export does not double-count. (After the
    # first import the file is moved to processed/; re-dropping it re-imports it.)
    _write_export(fin, "chase.csv", [["05/03/2026", "WHOLE FOODS MARKET", "82.14", ""]])
    finance.import_new()
    _write_export(fin, "chase.csv", [["05/03/2026", "WHOLE FOODS MARKET", "82.14", ""]])
    res = finance.import_new()
    assert res["added"] == 0 and res["skipped"] == 1
    assert len(finance._read_ledger()) == 1


def test_query_rejects_writes(fin):
    _write_export(fin, "a.csv", [["05/03/2026", "WHOLE FOODS MARKET", "82.14", ""]])
    finance.import_new()
    with pytest.raises(finance.FinanceError):
        finance.query("DELETE FROM ledger")
    with pytest.raises(finance.FinanceError):
        finance.query("SELECT 1; DROP TABLE ledger")


def test_query_and_summary(fin):
    _write_export(fin, "a.csv", [
        ["05/03/2026", "WHOLE FOODS MARKET", "82.14", ""],
        ["05/04/2026", "STARBUCKS", "6.45", ""],
        ["05/01/2026", "ACME CORP PAYROLL", "", "4200.00"],
    ])
    finance.import_new()
    spent = finance.query("SELECT ROUND(SUM(amount),2) s FROM ledger WHERE amount<0")
    assert spent[0]["s"] == -88.59
    s = finance.summary("2026-05")
    assert s["totals"]["income"] == 4200.0


def test_query_on_empty_ledger(fin):
    rows = finance.query("SELECT COUNT(*) n FROM ledger")
    assert rows[0]["n"] == 0
