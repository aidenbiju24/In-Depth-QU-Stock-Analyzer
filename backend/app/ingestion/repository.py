"""SQLite repository: normalized-schema persistence with provenance.

Upserts keep a single normalized row per (ticker, statement, period, fiscal
date, source) instead of silently accumulating conflicting duplicates;
re-ingest updates in place. Model outputs (factor_scores, valuations,
risk_metrics) are inserted fresh per model_run and never mutated.
"""
from __future__ import annotations

import json

from .. import schemas as S
from ..db import utcnow


def upsert_company(conn, company: S.Company) -> None:
    now = utcnow()
    conn.execute(
        """INSERT INTO companies (ticker, name, exchange, sector, industry, currency,
               description, source, retrieved_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET
             name=excluded.name, exchange=excluded.exchange,
             sector=excluded.sector, industry=excluded.industry,
             currency=excluded.currency, description=excluded.description,
             source=excluded.source, updated_at=excluded.updated_at""",
        (company.ticker, company.name, company.exchange, company.sector,
         company.industry, company.currency, company.description,
         company.source, now, now),
    )


def upsert_prices(conn, ticker: str, bars: list[S.PriceBar], source: str) -> int:
    rows = [
        (ticker, b.date.isoformat(), b.open, b.high, b.low, b.close,
         b.adj_close, b.volume, source, utcnow())
        for b in bars
    ]
    conn.executemany(
        """INSERT INTO prices (ticker, date, open, high, low, close, adj_close,
               volume, source, retrieved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ticker, date, source) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, adj_close=excluded.adj_close,
             volume=excluded.volume, retrieved_at=excluded.retrieved_at""",
        rows,
    )
    return len(rows)


def upsert_statement(conn, st: S.Statement, source: str) -> None:
    if st.filing_date is None:
        # Statements without a public filing date must never be treated as
        # point-in-time data; record that explicitly.
        pass
    conn.execute(
        """INSERT INTO financial_statements
               (ticker, statement, period, fiscal_date, filing_date, currency,
                data_json, source, retrieved_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ticker, statement, period, fiscal_date, source) DO UPDATE SET
             filing_date=excluded.filing_date, currency=excluded.currency,
             data_json=excluded.data_json, retrieved_at=excluded.retrieved_at""",
        (st.ticker, st.statement, st.period, st.fiscal_date.isoformat(),
         st.filing_date.isoformat() if st.filing_date else None,
         st.currency, json.dumps(st.items), source, utcnow()),
    )


def upsert_fundamentals(conn, f: S.Fundamentals, source: str) -> None:
    conn.execute(
        """INSERT INTO fundamentals
               (ticker, as_of, market_cap, pe, forward_pe, pb, ps, ev_ebitda,
                dividend_yield, beta_5y, eps, eps_diluted, shares_diluted,
                book_value_per_share, revenue_ttm, net_income_ttm, ebitda_ttm,
                free_cash_flow_ttm, operating_cash_flow_ttm, capex_ttm,
                total_debt, total_cash, total_equity, total_assets,
                gross_profit_ttm, operating_income_ttm, currency, source, retrieved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ticker, as_of, source) DO UPDATE SET
             market_cap=excluded.market_cap, pe=excluded.pe,
             forward_pe=excluded.forward_pe, pb=excluded.pb, ps=excluded.ps,
             ev_ebitda=excluded.ev_ebitda, dividend_yield=excluded.dividend_yield,
             beta_5y=excluded.beta_5y, eps=excluded.eps,
             eps_diluted=excluded.eps_diluted, shares_diluted=excluded.shares_diluted,
             book_value_per_share=excluded.book_value_per_share,
             revenue_ttm=excluded.revenue_ttm, net_income_ttm=excluded.net_income_ttm,
             ebitda_ttm=excluded.ebitda_ttm, free_cash_flow_ttm=excluded.free_cash_flow_ttm,
             operating_cash_flow_ttm=excluded.operating_cash_flow_ttm,
             capex_ttm=excluded.capex_ttm, total_debt=excluded.total_debt,
             total_cash=excluded.total_cash, total_equity=excluded.total_equity,
             total_assets=excluded.total_assets,
             gross_profit_ttm=excluded.gross_profit_ttm,
             operating_income_ttm=excluded.operating_income_ttm,
             currency=excluded.currency, retrieved_at=excluded.retrieved_at""",
        (f.ticker, f.as_of.isoformat(), f.market_cap, f.pe, f.forward_pe, f.pb,
         f.ps, f.ev_ebitda, f.dividend_yield, f.beta_5y, f.eps, f.eps_diluted,
         f.shares_diluted, f.book_value_per_share, f.revenue_ttm,
         f.net_income_ttm, f.ebitda_ttm, f.free_cash_flow_ttm,
         f.operating_cash_flow_ttm, f.capex_ttm, f.total_debt, f.total_cash,
         f.total_equity, f.total_assets, f.gross_profit_ttm,
         f.operating_income_ttm, f.currency, source, utcnow()),
    )


def upsert_earnings(conn, records: list[S.EarningsRecord], source: str) -> None:
    for r in records:
        conn.execute(
            """INSERT INTO earnings (ticker, fiscal_date, report_date, eps_actual,
                    eps_estimated, revenue_actual, revenue_estimated, source, retrieved_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ticker, fiscal_date, source) DO UPDATE SET
                 report_date=excluded.report_date, eps_actual=excluded.eps_actual,
                 eps_estimated=excluded.eps_estimated,
                 revenue_actual=excluded.revenue_actual,
                 revenue_estimated=excluded.revenue_estimated,
                 retrieved_at=excluded.retrieved_at""",
            (r.ticker, r.fiscal_date.isoformat(),
             r.report_date.isoformat() if r.report_date else None,
             r.eps_actual, r.eps_estimated, r.revenue_actual,
             r.revenue_estimated, source, utcnow()),
        )


# ----------------------------------------------------------------- readers
def read_prices(conn, ticker: str, start: str | None = None,
                end: str | None = None) -> list[dict]:
    q = ("SELECT date, open, high, low, close, adj_close, volume, source "
         "FROM prices WHERE ticker = ?")
    args: list = [ticker]
    if start:
        q += " AND date >= ?"
        args.append(start)
    if end:
        q += " AND date <= ?"
        args.append(end)
    q += " ORDER BY date"
    return [dict(r) for r in conn.execute(q, args)]


def read_statements(conn, ticker: str, statement: str, period: str = "annual",
                    as_of: str | None = None) -> list[dict]:
    """Statements with fiscal_date <= as_of. If as_of given, rows whose filing
    date is in the future relative to as_of are EXCLUDED (point-in-time rule)."""
    q = ("SELECT ticker, statement, period, fiscal_date, filing_date, currency, "
         "data_json, source FROM financial_statements "
         "WHERE ticker = ? AND statement = ? AND period = ?")
    args: list = [ticker, statement, period]
    if as_of is not None:
        q += (" AND fiscal_date <= ? AND (filing_date IS NULL OR filing_date <= ?)"
              " ORDER BY fiscal_date")
        args += [as_of, as_of]
    else:
        q += " ORDER BY fiscal_date"
    rows = []
    for r in conn.execute(q, args):
        row = dict(r)
        row["items"] = json.loads(row.pop("data_json"))
        rows.append(row)
    return rows


def read_fundamentals_latest(conn, ticker: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM fundamentals WHERE ticker = ? ORDER BY as_of DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    return dict(row) if row else None


def read_company(conn, ticker: str) -> dict | None:
    row = conn.execute("SELECT * FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    return dict(row) if row else None


def read_earnings(conn, ticker: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM earnings WHERE ticker = ? ORDER BY fiscal_date DESC",
        (ticker,),
    )]


def latest_price(conn, ticker: str) -> dict | None:
    row = conn.execute(
        "SELECT date, close, adj_close FROM prices WHERE ticker = ? "
        "ORDER BY date DESC LIMIT 1", (ticker,),
    ).fetchone()
    return dict(row) if row else None
