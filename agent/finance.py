"""Finance (Phase 3) — CSV import, rule-based categorisation, DuckDB analytics.

The pipeline is three files-on-disk stages, matching the repo's "git is the
database" philosophy:

  finance/imports/*.csv        raw exports you drop from a bank/card (any schema)
        │  import_new(): detect columns, normalise, categorise, de-dup
        ▼
  finance/transactions/ledger.csv   one canonical, append-only ledger
        │  read_csv_auto() via DuckDB
        ▼
  finance_query(sql) / summary()    answers like "what did I spend on dining?"

Design choices:
  - Import is fully deterministic (no LLM in the hot path): column detection is
    heuristic, categorisation is keyword rules from finance/categories.yaml. That
    keeps money data reproducible and testable; the agent refines categories via
    the playbook, not by guessing per-row.
  - De-dup by a content hash so re-importing the same export is a no-op.
  - Sign convention: outflow (spend) is negative, inflow (income) positive.
  - Queries are read-only: finance_query rejects anything but SELECT/WITH.
"""
from __future__ import annotations

import csv
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from . import config

LEDGER_REL = "finance/transactions/ledger.csv"
LEDGER_PATH = config.REPO_ROOT / LEDGER_REL
IMPORTS_DIR = config.FINANCE_DIR / "imports"
PROCESSED_DIR = IMPORTS_DIR / "processed"
CATEGORIES_YAML = config.FINANCE_DIR / "categories.yaml"
DASHBOARD_REL = "dashboards/finance.md"

LEDGER_FIELDS = ["id", "date", "description", "amount", "category", "account", "source"]


# --- Column detection --------------------------------------------------------
def _pick(headers: list[str], *needles: str) -> str | None:
    """First header whose lowercased name contains any needle."""
    low = {h: h.lower() for h in headers}
    for h in headers:
        if any(n in low[h] for n in needles):
            return h
    return None


def _parse_date(raw: str) -> str:
    """Best-effort date normalisation to ISO (YYYY-MM-DD); pass through if unknown."""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw


def _parse_amount(row: dict, amount_col: str | None, debit_col: str | None,
                  credit_col: str | None) -> float | None:
    """Signed amount: spend negative, income positive."""
    def num(v: str | None) -> float:
        v = (v or "").strip().replace(",", "").replace("$", "")
        if not v:
            return 0.0
        neg = v.startswith("(") and v.endswith(")")  # (12.34) accounting negative
        v = v.strip("()")
        try:
            f = float(v)
        except ValueError:
            return 0.0
        return -f if neg else f

    if amount_col:
        v = num(row.get(amount_col))
        return v if v != 0.0 else None
    if debit_col or credit_col:
        return num(row.get(credit_col)) - num(row.get(debit_col))
    return None


# --- Categorisation ----------------------------------------------------------
def load_categories() -> dict[str, list[str]]:
    if not CATEGORIES_YAML.exists():
        return {}
    data = yaml.safe_load(CATEGORIES_YAML.read_text()) or {}
    return {k: [str(x).lower() for x in (v or [])] for k, v in data.items()}


def categorize(description: str, rules: dict[str, list[str]]) -> str:
    desc = (description or "").lower()
    for category, needles in rules.items():
        if any(n in desc for n in needles):
            return category
    return "uncategorized"


# --- Ledger I/O --------------------------------------------------------------
def _row_id(date: str, description: str, amount: float, account: str) -> str:
    key = f"{date}|{description.strip().lower()}|{amount:.2f}|{account}".encode()
    return hashlib.sha1(key).hexdigest()[:16]


def _read_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    with open(LEDGER_PATH, newline="") as f:
        return list(csv.DictReader(f))


def _write_ledger(rows: list[dict]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r.get("date", ""), r.get("id", "")))
    with open(LEDGER_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        w.writerows(rows)


# --- Import ------------------------------------------------------------------
def _normalize_file(path: Path, rules: dict[str, list[str]]) -> list[dict]:
    """Parse one raw export into normalised ledger rows."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        date_col = _pick(headers, "date", "posted")
        desc_col = _pick(headers, "desc", "name", "memo", "payee", "details")
        amount_col = _pick(headers, "amount")
        debit_col = _pick(headers, "debit", "withdraw")
        credit_col = _pick(headers, "credit", "deposit")
        account = path.stem  # filename stands in for the account/source
        out: list[dict] = []
        for row in reader:
            date = _parse_date(row.get(date_col, "")) if date_col else ""
            desc = (row.get(desc_col, "") if desc_col else "").strip()
            amount = _parse_amount(row, amount_col, debit_col, credit_col)
            if amount is None or not (date or desc):
                continue
            out.append({
                "id": _row_id(date, desc, amount, account),
                "date": date,
                "description": desc,
                "amount": f"{amount:.2f}",
                "category": categorize(desc, rules),
                "account": account,
                "source": path.name,
            })
    return out


def import_new() -> dict:
    """Import every CSV in finance/imports/ into the ledger. De-dups by id and
    moves processed files to finance/imports/processed/. Returns a summary dict.
    """
    if config.KILL_SWITCH:
        return {"blocked": True, "added": 0, "files": 0, "skipped": 0}
    rules = load_categories()
    existing = _read_ledger()
    seen = {r["id"] for r in existing}
    added, skipped, files = 0, 0, 0
    new_rows: list[dict] = list(existing)
    for path in sorted(IMPORTS_DIR.glob("*.csv")):
        files += 1
        for row in _normalize_file(path, rules):
            if row["id"] in seen:
                skipped += 1
                continue
            seen.add(row["id"])
            new_rows.append(row)
            added += 1
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(PROCESSED_DIR / path.name))
    if added:
        _write_ledger(new_rows)
    return {"blocked": False, "added": added, "files": files, "skipped": skipped}


# --- Query (read-only DuckDB) ------------------------------------------------
class FinanceError(Exception):
    pass


def _ledger_con():
    import duckdb

    con = duckdb.connect(":memory:")
    if LEDGER_PATH.exists():
        # LEDGER_PATH is internal (never user input); read_csv_auto can't take a
        # bound parameter inside CREATE VIEW, so inline it with quotes escaped.
        safe = str(LEDGER_PATH).replace("'", "''")
        con.execute(
            f"CREATE VIEW ledger AS SELECT * FROM read_csv_auto('{safe}', header=true)"
        )
    else:  # empty ledger -> an empty, correctly-typed view so queries still run
        con.execute(
            "CREATE VIEW ledger AS SELECT * FROM (VALUES "
            "(NULL::VARCHAR, NULL::DATE, NULL::VARCHAR, NULL::DOUBLE, "
            "NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR)) "
            "AS t(id, date, description, amount, category, account, source) WHERE false"
        )
    return con


def query(sql: str, limit: int = 100) -> list[dict]:
    """Run a read-only SELECT/WITH query against the `ledger` view. Raises
    FinanceError on anything that isn't a single read-only statement."""
    stripped = sql.strip().rstrip(";").lstrip()
    if ";" in stripped:
        raise FinanceError("Only a single statement is allowed.")
    if not stripped[:6].lower() in ("select",) and not stripped[:4].lower() == "with":
        raise FinanceError("Only SELECT/WITH (read-only) queries are allowed.")
    con = _ledger_con()
    try:
        rel = con.execute(stripped)
        cols = [d[0] for d in rel.description]
        rows = rel.fetchmany(limit)
    except Exception as e:  # surface DuckDB errors as FinanceError
        raise FinanceError(str(e)) from e
    finally:
        con.close()
    return [dict(zip(cols, r)) for r in rows]


def summary(month: str | None = None) -> dict:
    """Spending by category. `month` is 'YYYY-MM' (defaults to all-time)."""
    where = ""
    params_note = "all time"
    if month:
        where = f"WHERE strftime(date, '%Y-%m') = '{month}'"
        params_note = month
    by_cat = query(
        f"SELECT category, ROUND(SUM(amount), 2) AS net, COUNT(*) AS n "
        f"FROM ledger {where} GROUP BY category ORDER BY net ASC"
    )
    totals = query(
        f"SELECT ROUND(SUM(CASE WHEN amount<0 THEN amount ELSE 0 END),2) AS spent, "
        f"ROUND(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END),2) AS income "
        f"FROM ledger {where}"
    )
    return {"period": params_note, "by_category": by_cat, "totals": totals[0] if totals else {}}
