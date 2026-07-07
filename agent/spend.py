"""Daily spend accounting + budget guard (PLAN.md §2.5).

MAX_TURNS caps a single turn; this caps a *day*. Every model run records its
token usage and an estimated USD cost (pricing per model from models.yaml,
with a conservative fallback) into a per-day row. Before each new turn we
check the day's total against DAILY_BUDGET_USD and refuse politely once it is
exceeded — the "can't wake up to a $400 bill" control.

Estimates, not invoices: prices drift and cache accounting is provider-
specific. The guard is deliberately conservative; the provider console's
spend cap remains the true backstop.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from . import config, providers

# Anthropic-style multipliers for cache traffic, applied to the input price.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


class BudgetExceeded(Exception):
    """Raised before a turn when today's estimated spend is over budget."""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.SESSION_DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS usage_daily (
                   day           TEXT PRIMARY KEY,
                   input_tokens  INTEGER NOT NULL DEFAULT 0,
                   output_tokens INTEGER NOT NULL DEFAULT 0,
                   cost_usd      REAL    NOT NULL DEFAULT 0
               )"""
        )


def estimate_cost(model: str, usage) -> float:
    """Estimated USD cost of one run's usage under `model`'s pricing."""
    price_in, price_out = providers.pricing_for(model)
    tokens_in = usage.input_tokens or 0
    tokens_out = usage.output_tokens or 0
    cache_read = getattr(usage, "cache_read_tokens", 0) or 0
    cache_write = getattr(usage, "cache_write_tokens", 0) or 0
    return (
        tokens_in * price_in
        + cache_read * price_in * _CACHE_READ_MULT
        + cache_write * price_in * _CACHE_WRITE_MULT
        + tokens_out * price_out
    ) / 1_000_000


def record(model: str, usage) -> None:
    """Add one run's usage to today's row. Best-effort; never blocks a turn."""
    try:
        cost = estimate_cost(model, usage)
        with _connect() as conn:
            conn.execute(
                """INSERT INTO usage_daily (day, input_tokens, output_tokens, cost_usd)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(day) DO UPDATE SET
                       input_tokens  = input_tokens  + excluded.input_tokens,
                       output_tokens = output_tokens + excluded.output_tokens,
                       cost_usd      = cost_usd      + excluded.cost_usd""",
                (
                    date.today().isoformat(),
                    usage.input_tokens or 0,
                    usage.output_tokens or 0,
                    cost,
                ),
            )
    except Exception:  # pragma: no cover - accounting must never break a turn
        pass


def today() -> dict:
    """Today's accumulated usage: {day, input_tokens, output_tokens, cost_usd}."""
    day = date.today().isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT input_tokens, output_tokens, cost_usd FROM usage_daily WHERE day = ?",
            (day,),
        ).fetchone()
    if not row:
        return {"day": day, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    return {"day": day, "input_tokens": row[0], "output_tokens": row[1], "cost_usd": row[2]}


def check_budget() -> None:
    """Raise BudgetExceeded if today's estimated spend is at/over the ceiling."""
    budget = config.DAILY_BUDGET_USD
    if budget <= 0:
        return
    spent = today()["cost_usd"]
    if spent >= budget:
        raise BudgetExceeded(
            f"Daily budget reached (${spent:.2f} of ${budget:.2f} est.)."
            " I'll take new requests tomorrow — or raise DAILY_BUDGET_USD."
        )
