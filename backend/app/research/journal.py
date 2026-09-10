"""Research journal: investment decision records + model-run audit trail.

Decisions are append-only (PROJECT_SPEC §35): recording a decision inserts a
new row; the outcome field can be updated later but historical reasoning is
never rewritten. Every model execution is stored in model_runs with inputs,
parameters, outputs, versions, and data timestamps.
"""
from __future__ import annotations

import json
from contextlib import suppress

from ..db import connect, today, utcnow

VALID_DECISIONS = ("BUY", "HOLD", "SELL", "WATCH")


def record_decision(
    ticker: str,
    decision: str,
    decision_date: str | None = None,
    price: float | None = None,
    quant_score: float | None = None,
    value_score: float | None = None,
    growth_score: float | None = None,
    quality_score: float | None = None,
    momentum_score: float | None = None,
    risk_score: float | None = None,
    dcf_fair_value: float | None = None,
    dcf_upside: float | None = None,
    position_size: float | None = None,
    thesis: str | None = None,
    catalysts: str | None = None,
    risks: str | None = None,
    model_run_id: int | None = None,
) -> int:
    """Append one decision row; returns its id. Never overwrites history."""
    d = (decision or "").strip().upper()
    if d not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}, got {decision!r}")
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO research_decisions
               (created_at, decision_date, ticker, price, quant_score,
                value_score, growth_score, quality_score, momentum_score,
                risk_score, dcf_fair_value, dcf_upside, decision, position_size,
                thesis, catalysts, risks, outcome, model_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (utcnow(), decision_date or today(), ticker.upper(), price,
             quant_score, value_score, growth_score, quality_score,
             momentum_score, risk_score, dcf_fair_value, dcf_upside, d,
             position_size, thesis, catalysts, risks, model_run_id),
        )
        return int(cur.lastrowid)


def update_outcome(decision_id: int, outcome: str) -> None:
    """Fill in the outcome of a past decision (only that field)."""
    with connect() as conn:
        conn.execute(
            "UPDATE research_decisions SET outcome = ? WHERE id = ?",
            (outcome, int(decision_id)),
        )


def list_decisions(ticker: str | None = None, limit: int = 200) -> list[dict]:
    q = "SELECT * FROM research_decisions"
    args: list = []
    if ticker:
        q += " WHERE ticker = ?"
        args.append(ticker.upper())
    q += " ORDER BY decision_date DESC, id DESC LIMIT ?"
    args.append(int(limit))
    with connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


def record_model_run(model: str, version: str, subject: str,
                     parameters: dict, output_summary: dict,
                     input_as_of: str | None = None,
                     source_data: dict | None = None) -> int:
    """Store one model execution for the audit trail."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO model_runs (model, version, subject, run_at,"
            " input_as_of, parameters, output, source_data)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (model, version, subject, utcnow(), input_as_of,
             json.dumps(parameters, default=str),
             json.dumps(output_summary, default=str),
             json.dumps(source_data or {}, default=str)),
        )
        return int(cur.lastrowid)


def list_model_runs(subject: str | None = None, model: str | None = None,
                    limit: int = 100) -> list[dict]:
    q = "SELECT id, model, version, subject, run_at, input_as_of FROM model_runs"
    conds, args = [], []
    if subject:
        conds.append("subject = ?")
        args.append(subject)
    if model:
        conds.append("model = ?")
        args.append(model)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


def get_model_run(run_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for k in ("parameters", "output", "source_data"):
        with suppress(TypeError, ValueError):
            d[k] = json.loads(d[k]) if d.get(k) else None
    return d


# ------------------------------------------------------------------ portfolio
def create_portfolio(name: str, benchmark: str = "SPY", cash: float = 0.0,
                     portfolio_id: str | None = None) -> str:
    import uuid
    pid = portfolio_id or uuid.uuid4().hex[:12]
    with connect() as conn:
        conn.execute(
            "INSERT INTO portfolios (id, name, benchmark, cash, created_at,"
            " updated_at) VALUES (?,?,?,?,?,?)",
            (pid, name, benchmark, cash, utcnow(), utcnow()),
        )
    return pid


def add_position(portfolio_id: str, ticker: str, quantity: float,
                 avg_cost: float | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO portfolio_positions
                   (portfolio_id, ticker, quantity, avg_cost, added_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(portfolio_id, ticker) DO UPDATE SET
                 quantity = excluded.quantity, avg_cost = excluded.avg_cost""",
            (portfolio_id, ticker.upper(), float(quantity), avg_cost, utcnow()),
        )


def list_portfolios() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM portfolios ORDER BY created_at DESC")]


def get_portfolio(portfolio_id: str) -> dict | None:
    with connect() as conn:
        p = conn.execute("SELECT * FROM portfolios WHERE id = ?",
                         (portfolio_id,)).fetchone()
        if p is None:
            return None
        d = dict(p)
        d["positions"] = [dict(r) for r in conn.execute(
            "SELECT ticker, quantity, avg_cost, added_at FROM portfolio_positions"
            " WHERE portfolio_id = ? ORDER BY ticker", (portfolio_id,))]
    return d
